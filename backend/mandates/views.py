"""REST API for families' mandates, requests, people and the ledger (BUILD_SPEC §10).

Views only translate HTTP to services; every state change goes through mandates.services.
"""

import json
import uuid

from accounts.models import Membership
from django.db.models import Q
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
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
        return Response(BeneficiarySerializer(family.beneficiaries.order_by("name"), many=True).data)
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
    fields = [f for f in ("name", "relationship", "allowed_products", "address") if f in data]
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
        return Response(PayeeSerializer(qs, many=True).data)
    services.require_funder(request.user, family)
    data = request.data.copy()
    if data.get("phone"):
        data["phone"] = normalize_phone(data["phone"]) or data["phone"]  # invalid numbers fail validation
    serializer = PayeeSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    # New payees start unverified; verification is an admin step.
    payee = serializer.save(family=family, verified=False)
    return Response(PayeeSerializer(payee).data, status=status.HTTP_201_CREATED)


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
    if data.get("basket_id"):  # an order from the payee's own price list: the server sets the amount
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
