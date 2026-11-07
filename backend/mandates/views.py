"""REST API for families' mandates, requests, people and the ledger (BUILD_SPEC §10).

Views only translate HTTP to services; every state change goes through mandates.services.
"""

import json
import uuid
from decimal import Decimal

from accounts.models import Membership
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from agent import drafting
from agent.llm import LLMError
from core.api import IsFamilyMember, current_family, current_membership, get_or_404
from core.phones import normalize_phone
from payments import payouts, rails

from . import dashboard, services
from .describe import coverage, describe_rule
from .models import Approval, Evidence, LedgerEntry, Mandate, Payee, Request, Upload
from .serializers import (BeneficiarySerializer, LedgerEntrySerializer, MandateSerializer, MemberSerializer,
                          PayeeSerializer, RequestDetailSerializer, RequestSerializer, display_name)
from .templates import TEMPLATES, validate_rules

PERMS = [IsFamilyMember]
EVIDENCE_KINDS = {k for k, _ in Evidence.KINDS}


def _require(data, *names):
    missing = [n for n in names if data.get(n) in (None, "")]
    if missing:
        raise ValidationError({n: "This field is required." for n in missing})


def _family_user(family, user_id):
    m = family.memberships.select_related("user").filter(user_id=user_id).first()
    if m is None:
        raise ValidationError({"user_id": "Not a member of this family"})
    return m.user


# --- Beneficiaries and payees -----------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes(PERMS)
def beneficiaries(request):
    family = current_family(request)
    if request.method == "GET":
        qs = family.beneficiaries.order_by("name")
        links = dict(family.shop_links.filter(active=True).values_list("beneficiary_id", "token"))
        return Response([{**row, "shop_link": links.get(b.id)}
                         for b, row in zip(qs, BeneficiarySerializer(qs, many=True).data)])
    _require(request.data, "name", "phone")
    b = services.register_beneficiary(family=family, name=request.data["name"], phone=request.data["phone"],
                                      registered_by=request.user,
                                      relationship=request.data.get("relationship", ""),
                                      allowed_products=request.data.get("allowed_products") or [],
                                      address=request.data.get("address", ""))
    return Response(BeneficiarySerializer(b).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes(PERMS)
def beneficiary_detail(request, pk):
    family = current_family(request)
    b = get_or_404(family.beneficiaries, pk=pk)
    services.require_funder(request.user, family)
    data = request.data
    if "phone" in data:
        services.change_beneficiary_phone(b, data["phone"], request.user)
    if "address" in data:
        services.change_beneficiary_address(b, data["address"], request.user)
    fields = [f for f in ("name", "relationship", "allowed_products") if f in data]
    for f in fields:
        setattr(b, f, data[f])
    if fields:
        b.save(update_fields=[*fields, "updated_at"])
    return Response(BeneficiarySerializer(b).data)


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def payees(request):
    family = current_family(request)
    if request.method == "GET":
        qs = Payee.objects.filter(Q(family=family) | Q(family__isnull=True)).order_by("name")
        links = dict(family.payee_links.filter(active=True).values_list("payee_id", "token"))
        return Response([{**row, "upload_link": links.get(p.id)}
                         for p, row in zip(qs, PayeeSerializer(qs, many=True).data)])
    services.require_funder(request.user, family)
    data = request.data.copy()
    if data.get("phone"):
        data["phone"] = normalize_phone(data["phone"]) or data["phone"]  # invalid numbers fail validation
    serializer = PayeeSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    # New payees start unverified; verification is an admin step.
    payee = serializer.save(family=family, verified=False)
    return Response(PayeeSerializer(payee).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes(PERMS)
def payee_detail(request, pk):
    """A funder changes the family payee's chat number (who may talk to the assistant as this payee). Money still
    only goes to the payee's PayPal account, and its upload link still needs Log in with PayPal."""
    family = current_family(request)
    payee = get_or_404(family.payees, pk=pk)
    services.require_funder(request.user, family)
    if "phone" in request.data:
        raw = request.data.get("phone") or ""
        phone = normalize_phone(raw) if raw else ""
        if raw and not phone:
            raise ValidationError({"phone": "Enter the number with its country code"})
        payee.phone = phone
        payee.save(update_fields=["phone", "updated_at"])
    return Response(PayeeSerializer(payee).data)


@api_view(["GET"])
@permission_classes(PERMS)
def phone_channel_config(request):
    """Whether chat by phone is on, the number to message, and the words a new phone sends first."""
    from django.conf import settings

    from agent import phone_channel

    number = settings.TWILIO_WHATSAPP_FROM.split(":")[-1]
    return Response({"enabled": phone_channel.is_configured(), "number": number,
                     "join": f"join {settings.PHONE_JOIN_CODE}" if settings.PHONE_JOIN_CODE else ""})


@api_view(["POST", "DELETE"])
@permission_classes(PERMS)
def payee_upload_link(request, pk):
    """A funder gets a payee's private upload link (POST; {"new": true} replaces it with a new secret) or turns
    it off (DELETE)."""
    family = current_family(request)
    payee = get_or_404(Payee.objects.filter(Q(family=family) | Q(family__isnull=True)), pk=pk)
    link = services.set_payee_link(family, payee, request.user, enabled=request.method == "POST",
                                   new=bool(request.data.get("new")))
    return Response({"payee": str(payee.id), "upload_link": link.token if link else None})


@api_view(["POST", "DELETE"])
@permission_classes(PERMS)
def beneficiary_shop_link(request, pk):
    """A funder gets the beneficiary's private shop link (POST; {"new": true} replaces it, {"reset_pin": true} issues a
    new PIN) or turns it off. A new link or PIN is returned once, to tell the person by phone."""
    family = current_family(request)
    b = get_or_404(family.beneficiaries, pk=pk)
    link, pin = services.set_shop_link(family, b, request.user, enabled=request.method == "POST",
                                       new=bool(request.data.get("new")), reset_pin=bool(request.data.get("reset_pin")))
    return Response({"beneficiary": str(b.id), "shop_link": link.token if link else None, "pin": pin})


@api_view(["GET"])
@permission_classes(PERMS)
def notifications(request):
    from .models import Notification

    qs = Notification.objects.filter(user=request.user).order_by("-created_at")
    return Response({"unread": qs.filter(read_at__isnull=True).count(),
                     "items": [{"id": str(n.id), "text": n.text, "request": str(n.request_id) if n.request_id else None,
                                "read": n.read_at is not None, "created_at": n.created_at} for n in qs[:20]]})


@api_view(["POST"])
@permission_classes(PERMS)
def notifications_read(request):
    from django.utils import timezone

    from .models import Notification

    Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return Response({"unread": 0})


# --- Public shop link (no sign-in) -------------------------------------------------------------------------

SHOP_COOKIE, SHOP_COOKIE_PATH, SHOP_SESSION_SECONDS = "hukama_shop", "/api/public/shop/", 30 * 24 * 3600


def _shop_unlocked(request, link):
    from django.core import signing

    try:
        data = signing.loads(request.COOKIES.get(SHOP_COOKIE, ""), salt="shop-session", max_age=SHOP_SESSION_SECONDS)
    except signing.BadSignature:
        return False
    return data.get("link") == str(link.id) and data.get("pin") == link.pin_hash[-12:]


def _active_shop(token):
    try:
        return services.active_shop_link(token)
    except services.ServiceError:
        raise NotFound("This shop link is not active")


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_shop_unlock(request, token):
    """The person enters the PIN the family told them; their phone then stays unlocked for 30 days."""
    from django.core import signing

    link = services.unlock_shop_link(_active_shop(token), request.data.get("pin"))
    response = Response({"unlocked": True})
    # Tied to this PIN: a PIN reset by the family locks every phone again.
    response.set_cookie(SHOP_COOKIE, signing.dumps({"link": str(link.id), "pin": link.pin_hash[-12:]}, salt="shop-session"),
                        max_age=SHOP_SESSION_SECONDS, path=SHOP_COOKIE_PATH, httponly=True, samesite="Lax",
                        secure=request.is_secure())
    return response

_SHOP_STATUS = {Request.APPROVED: "Paid, being prepared", Request.PAID: "Paid", Request.REFUSED: "Not approved",
                Request.FAILED: "Payment failed; the family will follow up", Request.ESCALATED: "Waiting for the family",
                Request.HELD_FRAUD: "Waiting for the family", Request.CONFIRMED_FRAUD: "Not approved",
                Request.INVOICED: "Sent to the family to pay"}


def _shop_order(r):
    tx = r.rail_transactions.order_by("-created_at").first()
    decision = r.latest_decision
    show_reasons = r.status == Request.REFUSED and decision and decision.decided_by == "POLICY"
    status_text = _SHOP_STATUS.get(r.status, "Being checked")
    if r.status in (Request.APPROVED, Request.PAID) and r.details.get("paid_by"):
        status_text = f"Paid by {r.details['paid_by']}"
    elif r.status == Request.INVOICED:
        status_text = f"Sent to {services._name(r.invoice_to)} to pay" if r.invoice_to else "Sent to everyone to pay"
    return {"id": str(r.id), "amount": f"{r.amount:.2f}", "currency": r.mandate.currency, "state": r.status,
            "status": status_text, "store": r.payee.name if r.payee else "", "fulfilment": r.fulfilment,
            "items": r.details.get("items", []), "delivery_fee": r.details.get("delivery_fee"),
            "to_fix": [x["detail"] for x in decision.rule_results if not x["passed"] and x.get("kind") != "mandate"]
            if show_reasons else [],
            "delivery": tx.get_last_mile_status_display() if tx and tx.last_mile_status != "N/A" else None,
            "collection_code": tx.collection_code if tx and tx.last_mile_status == "AWAITING_COLLECTION" else None,
            "created_at": r.created_at}


def _shop_cap(mandate, beneficiary):
    """Groceries left this period under the mandate's grocery cap (None when there is no cap)."""
    from .describe import coverage

    row = next((c for c in coverage(mandate, beneficiary) if c.get("product") == "groceries"), None)
    if not row or row.get("cap") is None:
        return None
    return {"left": f"{max(Decimal(str(row['cap'])) - Decimal(str(row['used'])), Decimal('0')):.2f}",
            "period": row.get("period")}


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_shop(request, token):
    """What the beneficiary sees: the store's price list, who they can ask, and their recent shopping.
    Until the PIN is entered on this phone, only their first name is shown."""
    link = _active_shop(token)
    b = link.beneficiary
    if not _shop_unlocked(request, link):
        return Response({"name": b.name.split()[0], "family": link.family.name, "unlocked": False})
    payload = []
    for m, stores in services.shop_mandates(link.family, b):
        payload.append({
            "id": str(m.id), "title": m.title, "currency": m.currency, "allowance": _shop_cap(m, b),
            "funders": [{"id": str(f.user_id), "name": services._name(f.user)}
                        for f in m.mandate_funders.select_related("user").order_by("created_at")],
            "stores": [{"id": str(s.id), "name": s.name, "items": s.catalogue.get("items", []),
                        "delivery_fee": s.catalogue.get("delivery_fee", "0")} for s in stores],
        })
    recent = Request.objects.filter(beneficiary=b, product="groceries", mandate__family=link.family) \
        .select_related("mandate", "payee", "invoice_to").prefetch_related("decisions").order_by("-created_at")[:8]
    return Response({"name": b.name.split()[0], "family": link.family.name, "address": b.address, "unlocked": True,
                     "mandates": payload, "orders": [_shop_order(r) for r in recent]})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_shop_order(request, token):
    """The beneficiary sends a shopping list: paid from the fund if it can, otherwise sent to the family to pay."""
    link = _active_shop(token)
    if not _shop_unlocked(request, link):
        return Response({"detail": "Enter your PIN first"}, status=status.HTTP_403_FORBIDDEN)
    d = request.data
    req = services.place_shop_order(link, mandate_id=d.get("mandate"), store_id=d.get("store"),
                                    lines=d.get("items") or [], fulfilment=d.get("fulfilment"), ask=d.get("ask") or "all",
                                    note=d.get("note", ""), idempotency_key=d.get("idempotency_key", ""))
    return Response(_shop_order(req), status=status.HTTP_201_CREATED)


# --- Public payee upload link (no sign-in) ----------------------------------------------------------------

_PUBLIC_STATUS = {Request.APPROVED: "Approved, payment on its way", Request.PAID: "Paid",
                  Request.REFUSED: "Not approved", Request.FAILED: "Payment failed; the family will follow up",
                  Request.ESCALATED: "Waiting for the family", Request.HELD_FRAUD: "Waiting for the family",
                  Request.CONFIRMED_FRAUD: "Not approved"}


def _needs(mandate):
    """What this payee must send for the mandate, in plain words (from its rules)."""
    needs = []
    for r in mandate.rules.all():
        if r.kind == "requires_invoice":
            needs.append("Your invoice, for exactly the amount you ask for")
        elif r.kind == "price_ceiling":
            needs.append("A quote with each item and its price")
        elif r.kind == "requires_evidence":
            label = r.params.get("label") or r.params.get("kind", "").replace("_", " ").lower()
            needs.append(f"A photo showing: {label}" if r.params.get("kind") == Evidence.MILESTONE_PHOTO
                         else f"Evidence: {label}")
    return needs


def _public_request(r):
    decision = r.latest_decision
    show_reasons = r.status == Request.REFUSED and decision and decision.decided_by == "POLICY"
    return {"id": str(r.id), "mandate": r.mandate.title, "amount": f"{r.amount:.2f}", "currency": r.mandate.currency,
            "status": _PUBLIC_STATUS.get(r.status, "Being checked"), "state": r.status,
            "can_add_files": r.status in (Request.NEW, Request.ASSESSED, Request.REFUSED) and not
            r.approvals.filter(action__in=(Approval.REJECT, Approval.REPORT_FRAUD)).exists(),
            # Only rule results the payee can act on (never fraud signals or funder notes).
            "to_fix": [x["detail"] for x in decision.rule_results if not x["passed"] and x.get("kind") != "mandate"]
            if show_reasons else [],
            "created_at": r.created_at}


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_payee(request, token):
    """What the payee sees on their link: who it is for, what to send, and how their requests are going."""
    try:
        link = services.active_payee_link(token)
    except services.ServiceError:
        raise NotFound("This upload link is not active")
    mandates = services.payee_mandates(link.family, link.payee)
    recent = Request.objects.filter(mandate__family=link.family, payee=link.payee).select_related("mandate") \
        .prefetch_related("decisions", "approvals").order_by("-created_at")[:10]
    from payments import identity

    verified = identity.verified_email(request, link)
    return Response({
        "payee": link.payee.name, "family": link.family.name,
        "paypal_login": {"required": identity.required(), "verified_as": verified,
                         "account": identity.mask(link.payee.paypal_email)},
        "mandates": [{"id": str(m.id), "title": m.title, "type": TEMPLATES[m.type].label, "currency": m.currency,
                      "needs": _needs(m)} for m in mandates],
        # Their request history only after the PayPal login (when required): a link alone reveals nothing.
        "requests": [_public_request(r) for r in recent] if verified or not identity.required() else [],
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([MultiPartParser])
def public_payee_send(request, token):
    """The payee sends a quote, invoice or photo: a new request to pay them, or a file for an open request."""
    try:
        link = services.active_payee_link(token)
    except services.ServiceError:
        raise NotFound("This upload link is not active")
    from payments import identity

    verified = identity.verified_email(request, link)
    if identity.required() and not verified:
        return Response({"detail": f"Log in with {link.payee.name}'s PayPal account first, so the family knows "
                                   "it is really you"}, status=status.HTTP_403_FORBIDDEN)
    f = request.FILES.get("file")
    if f is None:
        raise ValidationError({"file": "Attach a photo or scan"})
    d = request.data
    req = services.submit_via_payee_link(
        link, verified_email=verified or "", mandate_id=d.get("mandate"), kind=d.get("kind", ""), data=f.read(), content_type=f.content_type,
        name=f.name, amount=d.get("amount"), note=d.get("note", ""), request_id=d.get("request") or None,
        idempotency_key=d.get("idempotency_key", ""))
    return Response(_public_request(req), status=status.HTTP_201_CREATED)


# --- Mandates ---------------------------------------------------------------------------------------------

def _mandates(family):
    return family.mandates.prefetch_related("rules", "mandate_funders__user")


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_types(request):
    return Response([{"type": t.type, "label": t.label, "purpose": t.purpose, "priority": t.priority,
                      "required_rules": t.required_rules} for t in TEMPLATES.values()])


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def mandates(request):
    family = current_family(request)
    if request.method == "GET":
        qs = _mandates(family).exclude(status=Mandate.CLOSED).order_by("created_at")
        return Response(MandateSerializer(qs, many=True).data)
    data = request.data
    _require(data, "type", "title", "rules")
    if data["type"] not in TEMPLATES:
        raise ValidationError({"type": "Unknown mandate type"})
    co_funders = [_family_user(family, uid) for uid in data.get("co_funder_ids", []) if uid != request.user.id]
    mandate = services.create_mandate(family=family, type=data["type"], title=data["title"], rules=data["rules"],
                                      created_by=request.user, purpose_text=data.get("purpose_text", ""),
                                      co_funders=co_funders)
    return Response(MandateSerializer(mandate).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes(PERMS)
def mandate_draft(request):
    """Plain language -> a proposed mandate for the funder to check. Nothing is saved or signed here."""
    family = current_family(request)
    services.require_funder(request.user, family)
    _require(request.data, "text")
    try:
        draft = drafting.draft_mandate(request.data["text"], family)
    except LLMError as exc:
        return Response({"detail": f"The assistant could not draft this right now: {exc}"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    draft["rules"] = [{**r, "text": describe_rule(r["kind"], r.get("params"))} for r in draft["rules"]]
    return Response(draft)


@api_view(["POST"])
@permission_classes(PERMS)
def rules_preview(request):
    """Validate an edited rule set and describe it, before the funder confirms and signs."""
    _require(request.data, "type")
    rules = request.data.get("rules") or []
    if request.data["type"] not in TEMPLATES:
        raise ValidationError({"type": "Unknown mandate type"})
    return Response({"errors": validate_rules(request.data["type"], rules),
                     "rules": [{**r, "text": describe_rule(r.get("kind"), r.get("params"))} for r in rules]})


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_detail(request, pk):
    return Response(MandateSerializer(get_or_404(_mandates(current_family(request)), pk=pk)).data)


@api_view(["POST"])
@permission_classes(PERMS)
def mandate_funders(request, pk):
    family = current_family(request)
    mandate = get_or_404(family.mandates, pk=pk)
    if not services.is_owner(mandate, request.user):
        raise ValidationError({"detail": "Only the mandate owner can add funders"})
    _require(request.data, "user_id")
    services.add_funder(mandate, _family_user(family, request.data["user_id"]), added_by=request.user)
    return Response(MandateSerializer(mandate).data)


@api_view(["POST", "DELETE"])
@permission_classes(PERMS)
def mandate_contribution_link(request, pk):
    """Owner turns the pool's public PayPal link on (POST, a new token) or off (DELETE)."""
    mandate = get_or_404(current_family(request).mandates.prefetch_related("rules", "mandate_funders__user"), pk=pk)
    services.set_contribution_link(mandate, request.user, enabled=request.method == "POST")
    return Response(MandateSerializer(mandate).data)


@api_view(["GET"])
@permission_classes(PERMS)
def mandate_coverage(request, pk):
    """What each product has used this period, and who covered it (Isikhwama quick actions)."""
    family = current_family(request)
    mandate = get_or_404(family.mandates.prefetch_related("rules"), pk=pk)
    beneficiary = get_or_404(family.beneficiaries, pk=request.query_params.get("beneficiary"))
    return Response(coverage(mandate, beneficiary))


# --- Requests ---------------------------------------------------------------------------------------------

def _requests(family):
    return Request.objects.filter(mandate__family=family) \
        .select_related("mandate", "beneficiary", "payee", "requester_user", "risk_assessment")


SETTLE_LIMIT = 10


def _settle(family):
    """No worker runs on Render: bring a few in-flight payouts up to date before listing them."""
    from payments.models import RailTransaction

    moving = RailTransaction.objects.filter(request__mandate__family=family).filter(
        Q(status=RailTransaction.PENDING) | Q(last_mile_status__in=RailTransaction.IN_TRANSIT)) \
        .select_related("request__payee")[:SETTLE_LIMIT]
    for tx in moving:
        try:
            payouts.refresh(tx)
        except rails.RailError:
            pass


@api_view(["GET", "POST"])
@permission_classes(PERMS)
def requests_(request):
    family = current_family(request)
    if request.method == "GET":
        _settle(family)
        if request.query_params.get("inbox"):
            qs = services.inbox(request.user).select_related("requester_user", "risk_assessment")
        else:
            qs = _requests(family).order_by("-created_at")
            if s := request.query_params.get("status"):
                qs = qs.filter(status__in=s.split(","))
            if m := request.query_params.get("mandate"):
                qs = qs.filter(mandate_id=m)
        return Response(RequestSerializer(qs[:100], many=True).data)

    data = request.data
    _require(data, "mandate", "product")
    mandate = get_or_404(family.mandates, pk=data["mandate"])
    beneficiary = get_or_404(family.beneficiaries, pk=data["beneficiary"]) if data.get("beneficiary") else None
    payee = (get_or_404(Payee.objects.filter(Q(family=family) | Q(family__isnull=True)), pk=data["payee"])
             if data.get("payee") else services.sole_payee(mandate, data["product"]))
    fulfilment, details, amount = "", {}, data.get("amount")
    if data.get("items"):  # items from the store's own price list: the server sets the amount
        if payee is None:
            raise ValidationError({"payee": "Choose the store"})
        amount, details = services.grocery_items_order(payee, data["items"], data.get("fulfilment"), beneficiary)
        fulfilment = data["fulfilment"]
    elif data.get("basket_id"):  # a ready-made basket from the payee's price list
        if payee is None:
            raise ValidationError({"payee": "Choose who supplies this basket"})
        amount, details = services.grocery_order(payee, data["basket_id"], data.get("fulfilment"), beneficiary)
        fulfilment = data["fulfilment"]
    elif amount in (None, ""):
        raise ValidationError({"amount": "This field is required."})
    uploads = []
    for item in data.get("uploads") or []:
        if item.get("kind") not in EVIDENCE_KINDS:
            raise ValidationError({"uploads": f"Unknown evidence kind {item.get('kind')}"})
        uploads.append((get_or_404(family.uploads, pk=item.get("upload_id")), item["kind"]))
    req = services.submit_request(
        mandate=mandate, amount=amount, product=data["product"], beneficiary=beneficiary, payee=payee,
        channel=Request.APP, requester_user=request.user, requester_display=display_name(request.user),
        message_text=data.get("message_text", ""), uploads=uploads, fulfilment=fulfilment, details=details,
        idempotency_key=f"app-{data.get('idempotency_key') or uuid.uuid4()}")
    return Response(RequestDetailSerializer(req).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes(PERMS)
def request_detail(request, pk):
    req = get_or_404(_requests(current_family(request)).prefetch_related("evidence__upload", "decisions",
                                                                         "approvals__user"), pk=pk)
    tx = req.rail_transactions.order_by("-created_at").first()
    if tx is not None:
        try:
            payouts.refresh(tx)  # no webhooks locally; cheap when nothing is pending
        except rails.RailError:
            pass
        req.refresh_from_db()
    return Response(RequestDetailSerializer(req).data)


@api_view(["POST"])
@permission_classes(PERMS)
def request_approval(request, pk):
    req = get_or_404(_requests(current_family(request)), pk=pk)
    action = request.data.get("action")
    if action not in {a for a, _ in Approval.ACTIONS}:
        raise ValidationError({"action": "Choose APPROVE, REJECT, VERIFIED_SAFE or REPORT_FRAUD"})
    req = services.apply_approval(req, request.user, action, note=request.data.get("note", ""))
    return Response(RequestDetailSerializer(req).data)


# --- Uploads ----------------------------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes(PERMS)
@parser_classes([MultiPartParser])
def uploads(request):
    f = request.FILES.get("file")
    if f is None:
        raise ValidationError({"file": "Attach a file"})
    upload = services.create_upload(family=current_family(request), data=f.read(), content_type=f.content_type,
                                    name=f.name, user=request.user)
    return Response({"id": str(upload.id), "name": upload.name, "content_type": upload.content_type,
                     "size": upload.size}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes(PERMS)
def upload_file(request, pk):
    upload = get_or_404(Upload.objects.filter(family=current_family(request)), pk=pk)
    response = HttpResponse(bytes(upload.data), content_type=upload.content_type)
    response["Content-Disposition"] = f'inline; filename="{upload.name or upload.id}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


# --- Ledger and family ------------------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes(PERMS)
def ledger(request):
    family = current_family(request)
    qs = LedgerEntry.objects.filter(family=family).select_related("mandate").order_by("-created_at")
    if m := request.query_params.get("mandate"):
        qs = qs.filter(mandate_id=m)
    if r := request.query_params.get("request"):
        qs = qs.filter(request_id=r)
    names = {m.user_id: display_name(m.user) for m in family.memberships.select_related("user")}
    return Response(LedgerEntrySerializer(qs[:200], many=True, context={"user_names": names}).data)


@api_view(["GET"])
@permission_classes(PERMS)
def family(request):
    m = current_membership(request)
    members = m.family.memberships.select_related("user").order_by("created_at")
    return Response({"id": str(m.family.id), "name": m.family.name, "role": m.role,
                     "members": MemberSerializer(members, many=True).data})


@api_view(["POST"])
@permission_classes(PERMS)
def family_invite(request):
    """The admin adds a member; a new person's temporary password is returned once, to pass on privately."""
    d = request.data
    member, password = services.invite_member(
        current_family(request), request.user, email=d.get("email"), first_name=d.get("first_name"),
        last_name=d.get("last_name", ""), role=d.get("role") or Membership.FUNDER, country=d.get("country", ""),
        phone=d.get("phone", ""), paypal_email=d.get("paypal_email", ""))
    return Response({**MemberSerializer(member).data, "temporary_password": password},
                    status=status.HTTP_201_CREATED)


# --- Dashboard --------------------------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes(PERMS)
def dashboard_data(request):
    """Linked tables for the AG Studio dashboard (mandates, fundings, requests, ledger)."""
    family = current_family(request)
    _settle(family)
    return Response(dashboard.tables(family))


@api_view(["GET"])
@permission_classes(PERMS)
def dashboard_summary(request):
    return Response(dashboard.summary(current_family(request)))


MAX_LAYOUT_BYTES = 256 * 1024


@api_view(["GET", "PUT", "DELETE"])
@permission_classes(PERMS)
def dashboard_layout(request):
    """The family's saved dashboard (shared by every member). DELETE goes back to the default report."""
    from accounts.models import DashboardLayout

    family = current_family(request)
    if request.method == "GET":
        layout = DashboardLayout.objects.filter(family=family).first()
        return Response({"state": layout.state if layout else None,
                         "updated_at": layout.updated_at if layout else None})
    if request.method == "DELETE":
        DashboardLayout.objects.filter(family=family).delete()
        return Response({"state": None})
    state = request.data.get("state")
    if not isinstance(state, dict) or not isinstance(state.get("pages"), list):
        raise ValidationError({"state": "Send the dashboard state with its pages"})
    if len(json.dumps(state)) > MAX_LAYOUT_BYTES:
        raise ValidationError({"state": "This dashboard is too large to save"})
    layout, _ = DashboardLayout.objects.update_or_create(family=family, defaults={"state": state,
                                                                                "updated_by": request.user})
    return Response({"state": layout.state, "updated_at": layout.updated_at})
