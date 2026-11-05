"""State changes for mandates. Views, the agent and seed_demo go through these functions, never raw saves.

Every state change writes an append-only LedgerEntry.
"""

import hashlib
import secrets
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Membership
from core.phones import find_phones, normalize_phone

from . import signing
from .models import (Approval, Beneficiary, BlockedPhone, Decision, Funding, LedgerEntry, Mandate, MandateFunder,
                     Payee, Request, RiskAssessment, Rule, Upload)
from .templates import validate_rules

SYSTEM = "SYSTEM"


class ServiceError(Exception):
    """A request the caller made that the rules do not allow; message is safe to show to users."""


def actor_of(user):
    return str(user.pk) if user is not None else SYSTEM


def record(mandate, event, actor, request=None, amount=None, **data):
    return LedgerEntry.objects.create(family_id=mandate.family_id, mandate=mandate, request=request,
                                      event=event, amount=amount, actor=actor, data=data)


def membership(user, family):
    return Membership.objects.filter(user=user, family=family).first()


def require_funder(user, family):
    m = membership(user, family)
    if m is None or not m.can_fund:
        raise ServiceError("Only the family's funders can do this")
    return m


@transaction.atomic
def invite_member(family, by, *, email, first_name, last_name="", role=Membership.FUNDER, country="", phone="",
                  paypal_email=""):
    """Admin adds a family member. A new person gets an account and a one-time temporary password to pass on.
    Returns (membership, temporary_password or None when the person already had an account)."""
    from django.contrib.auth import get_user_model
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    m = membership(by, family)
    if m is None or m.role != Membership.ADMIN:
        raise ServiceError("Only the family's admin can invite members")
    email = (email or "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise ServiceError("Enter a valid email address")
    if not (first_name or "").strip():
        raise ServiceError("Enter their first name")
    if role not in (Membership.FUNDER, Membership.VIEWER):
        raise ServiceError("Invite members as a funder or a viewer")
    if phone:
        phone = normalize_phone(phone)
        if not phone:
            raise ServiceError("Enter the phone number with its country code")
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    password = None
    if user is None:
        password = secrets.token_urlsafe(9)
        user = User.objects.create_user(username=email, email=email, password=password,
                                        first_name=first_name.strip(), last_name=(last_name or "").strip())
    elif Membership.objects.filter(user=user).exists():
        raise ServiceError("This person already belongs to a family")
    member = Membership.objects.create(user=user, family=family, role=role, country=(country or "").upper()[:2],
                                       phone=phone or "", paypal_email=paypal_email or email)
    return member, password


# --- Mandates ---------------------------------------------------------------------------------------------

def _normalise_rules(rules):
    return [{"kind": r["kind"], "params": r.get("params") or {}, "position": i} for i, r in enumerate(rules)]


@transaction.atomic
def create_mandate(*, family, type, title, rules, created_by, purpose_text="", currency="USD", expires_at=None,
                   co_funders=()):
    """Validate rules against the template, save, sign and activate. `created_by` becomes the OWNER."""
    require_funder(created_by, family)
    rules = _normalise_rules(rules)
    if errors := validate_rules(type, rules):
        raise ServiceError("; ".join(errors))
    mandate = Mandate.objects.create(family=family, type=type, title=title, purpose_text=purpose_text,
                                     currency=currency, expires_at=expires_at, created_by=created_by,
                                     status=Mandate.ACTIVE)
    Rule.objects.bulk_create(Rule(mandate=mandate, **r) for r in rules)
    MandateFunder.objects.create(mandate=mandate, user=created_by, role=MandateFunder.OWNER)
    for user in co_funders:
        add_funder(mandate, user, added_by=created_by)
    mandate.signature = signing.sign(mandate)
    mandate.save(update_fields=["signature", "updated_at"])
    record(mandate, LedgerEntry.RULES_CHANGED, actor_of(created_by), version=mandate.version, created=True,
           rules=rules)
    return mandate


def add_funder(mandate, user, added_by):
    require_funder(user, mandate.family)
    funder, _ = MandateFunder.objects.get_or_create(mandate=mandate, user=user,
                                                    defaults={"role": MandateFunder.CO_FUNDER})
    return funder


def is_owner(mandate, user):
    return MandateFunder.objects.filter(mandate=mandate, user=user, role=MandateFunder.OWNER).exists()


@transaction.atomic
def update_rules(mandate, rules, user):
    """Replace the rule set: owner only, bumps the version, re-signs and records the change."""
    if not is_owner(mandate, user):
        raise ServiceError("Only the mandate owner can change its rules")
    rules = _normalise_rules(rules)
    if errors := validate_rules(mandate.type, rules):
        raise ServiceError("; ".join(errors))
    mandate.rules.all().delete()
    Rule.objects.bulk_create(Rule(mandate=mandate, **r) for r in rules)
    mandate.version += 1
    mandate.signature = signing.sign(mandate)
    mandate.save(update_fields=["version", "signature", "updated_at"])
    record(mandate, LedgerEntry.RULES_CHANGED, actor_of(user), version=mandate.version, rules=rules)
    return mandate


def set_contribution_link(mandate, user, enabled):
    """Owner switches the pool's public PayPal link on (a new private token) or off."""
    from .templates import get_template

    if not is_owner(mandate, user):
        raise ServiceError("Only the mandate owner can share or stop its contribution link")
    if enabled and not get_template(mandate.type).public_contributions:
        raise ServiceError("Only pools can take contributions from people outside the family")
    mandate.contribute_token = secrets.token_urlsafe(12) if enabled else None
    mandate.save(update_fields=["contribute_token", "updated_at"])
    return mandate


# --- Funding and balances ---------------------------------------------------------------------------------

def create_funding(mandate, funder, amount, rail=Funding.PAYPAL, external_id=""):
    if mandate.status != Mandate.ACTIVE:
        raise ServiceError("This mandate is not accepting funds")
    if funder is not None and not mandate.mandate_funders.filter(user=funder).exists():
        raise ServiceError("Only this mandate's funders can fund it")
    amount = Decimal(amount)
    if amount <= 0:
        raise ServiceError("Amount must be positive")
    return Funding.objects.create(mandate=mandate, funder=funder, amount=amount, rail=rail, external_id=external_id)


@transaction.atomic
def mark_funding_captured(funding, external_id=None):
    """Idempotent: capturing twice records one FUNDED entry."""
    funding = Funding.objects.select_for_update().get(pk=funding.pk)
    if funding.status == Funding.CAPTURED:
        return funding
    funding.status = Funding.CAPTURED
    if external_id:
        funding.external_id = external_id
    funding.save(update_fields=["status", "external_id", "updated_at"])
    actor = actor_of(funding.funder) if funding.funder_id or not funding.contributor_name \
        else f"Local: {funding.contributor_name}"
    record(funding.mandate, LedgerEntry.FUNDED, actor, amount=funding.amount,
           funding_id=str(funding.id), rail=funding.rail, external_id=funding.external_id)
    if funding.for_request_id:
        settle_invoice(funding)  # a funder paid a shopping list: decide and pay it now
    return funding


@transaction.atomic
def record_refund(funding, refunded, refund_id="", chargeback=False):
    """Set how much of a captured funding PayPal gave back (idempotent: the total, not an increment)."""
    funding = Funding.objects.select_for_update().get(pk=funding.pk)
    refunded = min(max(Decimal(refunded), Decimal("0")), funding.amount)
    if funding.status != Funding.CAPTURED or refunded <= funding.refunded:
        return funding
    funding.refunded = refunded
    funding.save(update_fields=["refunded", "updated_at"])
    record(funding.mandate, LedgerEntry.REFUNDED, "PAYPAL", amount=refunded, funding_id=str(funding.id),
           refund_id=refund_id, chargeback=chargeback)
    return funding


def captured_total(mandate):
    """Money PayPal captured for the mandate, less anything later refunded or charged back."""
    totals = mandate.fundings.filter(status=Funding.CAPTURED).aggregate(t=Sum("amount"), r=Sum("refunded"))
    return (totals["t"] or Decimal("0")) - (totals["r"] or Decimal("0"))


def committed_total(mandate, exclude_request=None):
    qs = mandate.requests.filter(status__in=Request.COMMITTED)
    if exclude_request is not None:
        qs = qs.exclude(pk=exclude_request.pk)
    return qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")


def mandate_balance(mandate, exclude_request=None):
    """Captured funding minus approved (payout pending) and paid requests."""
    return captured_total(mandate) - committed_total(mandate, exclude_request)


def funder_contributions(mandate):
    """{user_id: captured amount} for every funder of the mandate (zero if they have not funded yet)."""
    totals = {f.user_id: Decimal("0") for f in mandate.mandate_funders.all()}
    for row in mandate.fundings.filter(status=Funding.CAPTURED, funder__isnull=False) \
            .values("funder_id").annotate(t=Sum("amount"), r=Sum("refunded")):
        totals[row["funder_id"]] = row["t"] - row["r"]
    return totals


# --- Beneficiaries ----------------------------------------------------------------------------------------

def register_beneficiary(*, family, name, phone, registered_by, relationship="", allowed_products=(), address=""):
    require_funder(registered_by, family)
    e164 = normalize_phone(phone)
    if not e164:
        raise ServiceError("Enter a valid phone number")
    return Beneficiary.objects.create(family=family, name=name, phone=e164, relationship=relationship,
                                      allowed_products=list(allowed_products), registered_by=registered_by,
                                      address=address.strip()[:200], verified_at=timezone.now())


def change_beneficiary_address(beneficiary, address, user):
    """Deliveries only go to the registered address, so changing it is watched like a number change."""
    require_funder(user, beneficiary.family)
    address = (address or "").strip()[:200]
    if address != beneficiary.address:
        beneficiary.address = address
        beneficiary.address_changed_at = timezone.now()
        beneficiary.save(update_fields=["address", "address_changed_at", "updated_at"])
    return beneficiary


def change_beneficiary_phone(beneficiary, phone, user):
    """Changing a number triggers the BENEFICIARY_RECENTLY_CHANGED fraud signal for 72 hours."""
    require_funder(user, beneficiary.family)
    e164 = normalize_phone(phone)
    if not e164:
        raise ServiceError("Enter a valid phone number")
    if e164 != beneficiary.phone:
        beneficiary.phone = e164
        beneficiary.phone_changed_at = timezone.now()
        beneficiary.save(update_fields=["phone", "phone_changed_at", "updated_at"])
    return beneficiary


# --- Requests: assess -> decide -> execute ----------------------------------------------------------------

def _intent_analyzer():
    from agent import fraud
    return fraud.default_intent_analyzer()


ALLOWED_UPLOAD_TYPES = Upload.IMAGE_TYPES + ("application/pdf",)


def create_upload(*, family, data, content_type, name="", user=None, phone=""):
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise ServiceError("Send a photo (JPEG, PNG, WebP) or a PDF")
    if not data:
        raise ServiceError("The file is empty")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise ServiceError("The file is too large (8 MB maximum)")
    return Upload.objects.create(family=family, uploaded_by=user, uploaded_by_phone=normalize_phone(phone) or phone,
                                 name=name[:200], content_type=content_type, size=len(data),
                                 sha256=hashlib.sha256(data).hexdigest(), data=data)


def _extract(evidence):
    from agent import extraction
    return extraction.extract(evidence)


def attach_evidence(request, upload, kind, extractor=None):
    """Attach an uploaded file as evidence and read it. A failed read leaves the evidence unread,
    which the rules treat as missing — never as passed."""
    from agent.extraction import ExtractionError
    from agent.llm import LLMError

    if upload.family_id != request.mandate.family_id:
        raise ServiceError("That file belongs to another family")
    evidence = request.evidence.create(kind=kind, upload=upload)
    try:
        (extractor or _extract)(evidence)
    except (ExtractionError, LLMError) as exc:
        evidence.extracted = {}
        evidence.model_name = ""
        evidence.save(update_fields=["extracted", "model_name", "updated_at"])
        evidence.error = str(exc)
    return evidence


@transaction.atomic
def submit_request(*, mandate, amount, idempotency_key, channel=Request.APP, requester_user=None,
                   requester_phone="", requester_display="", beneficiary=None, payee=None, product="",
                   message_text="", evidence=(), uploads=(), summary_en="", fulfilment="", details=None,
                   intent_analyzer=None, extractor=None, now=None):
    """Create a Request, then run fraud.assess -> policy.evaluate -> execute_decision.

    Creating a request never pays by itself; only an APPROVE decision leads to a payout.
    Re-submitting the same idempotency_key returns the existing request untouched.
    `evidence` is a list of {"kind", "extracted"} dicts and `uploads` a list of (Upload, kind) pairs, both
    attached (uploads are read by the vision model) before the policy runs.
    """
    from agent import fraud, policy

    existing = Request.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return existing
    if requester_user is not None and membership(requester_user, mandate.family) is None:
        raise ServiceError("You are not a member of this family")
    amount = clean_amount(amount)
    request = Request.objects.create(
        mandate=mandate, amount=amount, idempotency_key=idempotency_key, channel=channel,
        requester_user=requester_user, requester_phone=normalize_phone(requester_phone) or requester_phone,
        requester_display=requester_display, beneficiary=beneficiary, payee=payee, product=product,
        message_text=message_text, summary_en=summary_en, fulfilment=fulfilment, details=details or {})
    record(mandate, LedgerEntry.REQUESTED, actor_of(requester_user) if requester_user else
           (request.requester_phone or SYSTEM), request=request, amount=request.amount, product=product,
           channel=channel, **({"fulfilment": fulfilment} if fulfilment else {}))
    for item in evidence:
        request.evidence.create(kind=item["kind"], extracted=item.get("extracted") or {},
                                model_name=item.get("model_name", ""))
    for upload, kind in uploads:
        attach_evidence(request, upload, kind, extractor=extractor)

    risk = fraud.assess(request, intent_analyzer=intent_analyzer or _intent_analyzer(), now=now)
    request.status = Request.ASSESSED
    request.save(update_fields=["status", "updated_at"])
    record(mandate, LedgerEntry.ASSESSED, "POLICY", request=request, score=risk.score, level=risk.level,
           signals=[s["signal"] for s in risk.signals], ai_flags=[f["flag"] for f in risk.ai_flags])

    lock_mandate(mandate)  # caps and balance are checked and committed one request at a time
    policy.evaluate(request, now=now)
    execute_decision(request)
    request.refresh_from_db()
    return request


def clean_amount(amount):
    """A positive amount in cents (PayPal pays whole cents only)."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ServiceError("Enter the amount as a number")
    if not value.is_finite() or value <= 0:
        raise ServiceError("The amount must be positive")
    if value != value.quantize(Decimal("0.01")):
        raise ServiceError("Use at most two decimal places")
    return value.quantize(Decimal("0.01"))


def lock_mandate(mandate):
    """Serialise decisions on one mandate so two requests at the same moment cannot both use the last of a
    cap or the balance (e.g. two siblings topping up the same airtime together)."""
    return Mandate.objects.select_for_update().get(pk=mandate.pk)


def reassess(request, intent_analyzer=None, now=None):
    """Re-run assessment and policy after new evidence (e.g. a revised quote). Only for undecided or
    refused requests; never touches a request that is paid, pending payment or held for fraud."""
    from agent import fraud, policy

    if request.status not in (Request.NEW, Request.ASSESSED, Request.REFUSED):
        raise ServiceError("This request can no longer be re-checked")
    if request.approvals.filter(action__in=(Approval.REJECT, Approval.REPORT_FRAUD)).exists():
        raise ServiceError("A funder rejected this request; send a new request instead")
    with transaction.atomic():
        previous = RiskAssessment.objects.filter(request=request).first()
        risk = fraud.assess(request, intent_analyzer=intent_analyzer or _intent_analyzer(), now=now)
        if previous is not None and previous.score > risk.score:
            fraud.keep_higher_risk(risk, previous)  # a re-check can add risk, never remove it
        lock_mandate(request.mandate)
        policy.evaluate(request, now=now)
        execute_decision(request)
    request.refresh_from_db()
    return request


def sole_payee(mandate, product=""):
    """The one allowed payee for `product`: e.g. the mobile money provider for airtime and the grocer for
    groceries in the same support mandate. Payees that list no products supply anything. None if ambiguous."""
    ids = {str(i) for r in mandate.rules.all() if r.kind == "allowed_payees" for i in r.params.get("payee_ids", [])}
    payees = list(Payee.objects.filter(pk__in=ids))
    if product:
        payees = [p for p in payees if not p.products or product in p.products] or payees
    return payees[0] if len(payees) == 1 else None


def basket(payee, basket_id):
    found = next((b for b in (payee.catalogue or {}).get("baskets", []) if b.get("id") == basket_id), None)
    if found is None:
        raise ServiceError(f"{payee.name} has no basket called {basket_id!r}")
    return found


MAX_ORDER_LINES = 40
MAX_LINE_QUANTITY = 50


def grocery_items_order(payee, lines, fulfilment, beneficiary):
    """Price a list of {item_id, quantity} from the payee's own price list (the client never sets prices).
    Delivery only ever goes to the beneficiary's registered address. Returns (amount, details)."""
    if fulfilment not in (Request.COLLECT, Request.DELIVERY):
        raise ServiceError("Choose collect in store or home delivery")
    catalogue = {i["id"]: i for i in (payee.catalogue or {}).get("items", [])}
    wanted = {}
    for line in lines or []:
        try:
            item_id, quantity = str(line.get("item_id") or line.get("id")), int(line.get("quantity") or 0)
        except (AttributeError, TypeError, ValueError):
            raise ServiceError("Each item needs an id and a whole quantity")
        if item_id not in catalogue:
            raise ServiceError(f"{payee.name} does not sell {item_id!r}")
        if quantity < 0 or quantity > MAX_LINE_QUANTITY:
            raise ServiceError(f"Choose between 1 and {MAX_LINE_QUANTITY} of each item")
        if quantity:
            wanted[item_id] = wanted.get(item_id, 0) + quantity
    if not wanted:
        raise ServiceError("Choose at least one item")
    if len(wanted) > MAX_ORDER_LINES:
        raise ServiceError(f"Order at most {MAX_ORDER_LINES} different items at a time")
    items, subtotal = [], Decimal("0")
    for item_id, quantity in wanted.items():
        item = catalogue[item_id]
        price = Decimal(str(item["price"]))
        line_total = price * quantity
        subtotal += line_total
        items.append({"id": item_id, "name": item["name"], "size": item.get("size", ""), "quantity": quantity,
                      "price": f"{price:.2f}", "line_total": f"{line_total:.2f}"})
    details = {"items": items, "subtotal": f"{subtotal:.2f}", "store": payee.name}
    amount = subtotal
    if fulfilment == Request.DELIVERY:
        if beneficiary is None or not beneficiary.address:
            raise ServiceError("Home delivery needs the beneficiary's registered address")
        fee = Decimal(str((payee.catalogue or {}).get("delivery_fee", "0")))
        amount += fee
        details.update(delivery_fee=f"{fee:.2f}", address=beneficiary.address)
    return amount.quantize(Decimal("0.01")), details


def grocery_order(payee, basket_id, fulfilment, beneficiary):
    """Price an order from the payee's own catalogue (the client never sets the amount).
    Delivery only ever goes to the beneficiary's registered address. Returns (amount, details)."""
    if fulfilment not in (Request.COLLECT, Request.DELIVERY):
        raise ServiceError("Choose collect in store or home delivery")
    chosen = basket(payee, basket_id)
    amount = Decimal(str(chosen["price"]))
    details = {"basket_id": chosen["id"], "basket": chosen["name"], "items": chosen.get("items", []),
               "basket_price": f"{amount:.2f}", "store": payee.name}
    if fulfilment == Request.DELIVERY:
        if beneficiary is None or not beneficiary.address:
            raise ServiceError("Home delivery needs the beneficiary's registered address")
        fee = Decimal(str((payee.catalogue or {}).get("delivery_fee", "0")))
        amount += fee
        details.update(delivery_fee=f"{fee:.2f}", address=beneficiary.address)
    return amount, details


def execute_decision(request):
    """Act on the latest policy decision: pay on APPROVE; ESCALATED / HELD_FRAUD wait in the funders' inbox."""
    from payments.payouts import pay_request

    if request.status == Request.APPROVED:
        return pay_request(request)
    if request.status == Request.HELD_FRAUD:
        risk = request.risk_assessment
        record(request.mandate, LedgerEntry.FRAUD_HELD, "POLICY", request=request, amount=request.amount,
               score=risk.score, signals=[s["signal"] for s in risk.signals])
    return None


def inbox(user):
    """Requests waiting for this funder: escalations, fraud holds, and shopping lists sent to them to pay."""
    from django.db.models import Q

    waiting = Q(status__in=(Request.ESCALATED, Request.HELD_FRAUD)) | \
        (Q(status=Request.INVOICED) & (Q(invoice_to__isnull=True) | Q(invoice_to=user)))
    return Request.objects.filter(waiting, mandate__mandate_funders__user=user) \
        .select_related("mandate", "beneficiary", "payee").distinct().order_by("-created_at")


ALLOWED_ACTIONS = {
    Request.ESCALATED: {Approval.APPROVE, Approval.REJECT, Approval.REPORT_FRAUD},
    Request.HELD_FRAUD: {Approval.VERIFIED_SAFE, Approval.REJECT, Approval.REPORT_FRAUD},
    Request.INVOICED: {Approval.REJECT},  # paying is the approval; any funder asked may decline it for the family
}


@transaction.atomic
def apply_approval(request, user, action, note=""):
    """A funder's answer to an escalation or fraud hold. Hard refusals cannot be overridden."""
    from agent import fraud, policy

    request = Request.objects.select_for_update().get(pk=request.pk)
    lock_mandate(request.mandate)
    if not request.mandate.mandate_funders.filter(user=user).exists():
        raise ServiceError("Only this mandate's funders can approve its requests")
    allowed = ALLOWED_ACTIONS.get(request.status)
    if allowed is None:
        raise ServiceError(f"This request is {request.get_status_display().lower()} and cannot be approved "
                           "or rejected" + (" (a refusal needs a rule change)" if request.status == Request.REFUSED
                                            else ""))
    if action not in allowed:
        raise ServiceError(f"{action} is not possible for a request that is {request.get_status_display().lower()}")
    if request.status == Request.INVOICED and request.invoice_to_id not in (None, user.pk):
        raise ServiceError("This shopping list was sent to someone else")
    if action == Approval.VERIFIED_SAFE and not note.strip():
        raise ServiceError("Say how you verified it, e.g. that you called the beneficiary on the registered number")

    Approval.objects.create(request=request, user=user, action=action, note=note)
    actor = actor_of(user)

    if action in (Approval.APPROVE, Approval.VERIFIED_SAFE):
        record(request.mandate, LedgerEntry.APPROVED_BY_FUNDER, actor, request=request, amount=request.amount,
               action=action, note=note)
        result = policy.check(request, funder_verified=True)
        Decision.objects.create(request=request, outcome=result.outcome, reason=result.reason,
                                rule_results=result.rule_results, decided_by=actor)
        request.status = Request.APPROVED if result.outcome == Decision.APPROVE else Request.REFUSED
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.DECIDED, actor, request=request, amount=request.amount,
               outcome=result.outcome, reason=result.reason)
        execute_decision(request)
    elif action == Approval.REJECT:
        Decision.objects.create(request=request, outcome=Decision.REFUSE, reason=f"Rejected by a funder. {note}".strip(),
                                decided_by=actor)
        request.status = Request.REFUSED
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.DECIDED, actor, request=request, amount=request.amount,
               outcome=Decision.REFUSE, note=note)
        if request.channel == Request.SHOP:
            notify(_others(request, user), f"{_name(user)} declined {_whose(request)} shopping list "
                                           f"(${request.amount:.2f}).", request)
    else:  # REPORT_FRAUD
        registered = fraud.registered_phones(request.mandate.family)
        suspects = [p for p in [request.requester_phone, *find_phones(request.message_text)]
                    if p and p not in registered]
        for phone in dict.fromkeys(suspects):
            BlockedPhone.objects.get_or_create(family=request.mandate.family, phone=phone,
                                               defaults={"reason": note, "request": request})
        request.status = Request.CONFIRMED_FRAUD
        request.save(update_fields=["status", "updated_at"])
        record(request.mandate, LedgerEntry.FRAUD_CONFIRMED, actor, request=request, amount=request.amount,
               blocked=suspects, note=note)
    request.refresh_from_db()
    return request


# --- Payee upload links -----------------------------------------------------------------------------------

LINK_UPLOADS_PER_DAY = 20
LINK_EVIDENCE_KINDS = ("QUOTE", "INVOICE", "MILESTONE_PHOTO")


def payee_mandates(family, payee):
    """Active mandates of `family` that may pay `payee` (it is in their allowed payees)."""
    ids = str(payee.id)
    return [m for m in Mandate.objects.filter(family=family, status=Mandate.ACTIVE).prefetch_related("rules")
            .order_by("created_at")
            if any(r.kind == "allowed_payees" and ids in map(str, r.params.get("payee_ids", [])) for r in m.rules.all())]


@transaction.atomic
def set_payee_link(family, payee, user, enabled, new=False):
    """A funder gets a payee's upload link (the active one, or a fresh secret when `new` or none exists) or
    turns it off. Returns the active PayeeLink or None."""
    from .models import PayeeLink

    require_funder(user, family)
    if payee.family_id not in (None, family.id):
        raise ServiceError("That payee belongs to another family")
    current = PayeeLink.objects.select_for_update().filter(family=family, payee=payee, active=True).first()
    if enabled and current is not None and not new:
        return current
    PayeeLink.objects.filter(family=family, payee=payee, active=True).update(active=False)
    if not enabled:
        return None
    if not payee_mandates(family, payee):
        raise ServiceError(f"No mandate can pay {payee.name} yet. Add them to a mandate's payees first")
    return PayeeLink.objects.create(family=family, payee=payee, token=secrets.token_urlsafe(16), created_by=user)


def active_payee_link(token):
    from .models import PayeeLink

    link = PayeeLink.objects.filter(token=token, active=True).select_related("family", "payee").first() \
        if token else None
    if link is None:
        raise ServiceError("This upload link is not active")
    return link


def _link_upload(link, data, content_type, name):
    from datetime import timedelta

    since = timezone.now() - timedelta(hours=24)
    if Upload.objects.filter(payee_link=link, created_at__gte=since).count() >= LINK_UPLOADS_PER_DAY:
        raise ServiceError("Too many files today through this link. Try again tomorrow or contact the family")
    upload = create_upload(family=link.family, data=data, content_type=content_type, name=name,
                           phone=link.payee.phone)
    upload.payee_link = link
    upload.save(update_fields=["payee_link", "updated_at"])
    return upload


def submit_via_payee_link(link, *, mandate_id, kind, data, content_type, name="", amount=None, note="",
                          request_id=None, idempotency_key="", intent_analyzer=None, extractor=None):
    """A payee sends a quote, invoice or photo through their link.

    With `request_id` the file is added to one of this payee's own open requests and re-checked; otherwise it
    becomes a new request to pay this payee. The payee is always the link's payee, so nothing sent here can
    pay anyone else, and fraud checks and the rules decide exactly as for any other request.
    """
    if kind not in LINK_EVIDENCE_KINDS:
        raise ServiceError("Send a quote, an invoice or a progress photo")
    payee = link.payee
    if request_id:
        request = Request.objects.filter(pk=request_id, mandate__family=link.family, payee=payee).first() \
            if _is_uuid(request_id) else None
        if request is None:
            raise ServiceError("No such request for you")
        if request.status not in (Request.NEW, Request.ASSESSED, Request.REFUSED) or \
                request.approvals.filter(action__in=(Approval.REJECT, Approval.REPORT_FRAUD)).exists():
            raise ServiceError("This request is already decided; send a new one instead")
        upload = _link_upload(link, data, content_type, name)
        attach_evidence(request, upload, kind, extractor=extractor)
        return reassess(request, intent_analyzer=intent_analyzer)

    key = f"link-{link.id}-{idempotency_key or secrets.token_hex(8)}"[:100]
    if existing := Request.objects.filter(idempotency_key=key).first():
        return existing  # the same form sent twice
    mandate = next((m for m in payee_mandates(link.family, payee) if str(m.id) == str(mandate_id)), None)
    if mandate is None:
        raise ServiceError("Choose what this is for")
    if amount in (None, ""):
        raise ServiceError("Enter the amount to be paid")
    amount = clean_amount(amount)
    from .templates import get_template
    product = (payee.products or [None])[0] or get_template(mandate.type).default_product or "other"
    upload = _link_upload(link, data, content_type, name)
    return submit_request(
        mandate=mandate, amount=amount, product=product, payee=payee, channel=Request.LINK,
        requester_phone=payee.phone, requester_display=payee.name, message_text=(note or "").strip()[:1000],
        summary_en=f"{payee.name} sent a {kind.replace('_', ' ').lower()} for {amount:.2f}",
        uploads=[(upload, kind)], idempotency_key=key,
        intent_analyzer=intent_analyzer, extractor=extractor)


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False



# --- Notifications ----------------------------------------------------------------------------------------

def notify(users, text, request=None):
    from .models import Notification

    users = [u for u in users if u is not None]
    if not users:
        return
    family_id = request.mandate.family_id if request is not None else None
    Notification.objects.bulk_create(Notification(family_id=family_id or Membership.objects.get(user=u).family_id,
                                                  user=u, request=request, text=text[:300]) for u in users)


def _name(user):
    return user.first_name or user.get_full_name() or user.username


def _whose(request):
    return f"{request.beneficiary.name.split()[0]}'s" if request.beneficiary else "the"


def _addressed(request):
    """The funders a shopping list was sent to: one funder, or every funder of the mandate."""
    if request.invoice_to_id:
        return [request.invoice_to]
    return [f.user for f in request.mandate.mandate_funders.select_related("user")]


def _others(request, user):
    return [u for u in _addressed(request) if u.pk != user.pk]


# --- Shop links and shopping lists (beneficiaries choose for themselves) ---------------------------------

SHOP_ORDERS_PER_DAY = 10


def shop_mandates(family, beneficiary):
    """Active mandates that cover this beneficiary's groceries, each with its store(s) that have a price list."""
    result = []
    for m in Mandate.objects.filter(family=family, status=Mandate.ACTIVE).prefetch_related("rules") \
            .order_by("created_at"):
        rules = list(m.rules.all())
        covered = any(r.kind == "allowed_beneficiaries" and str(beneficiary.id) in map(str, r.params.get(
            "beneficiary_ids", [])) for r in rules)
        groceries = any(r.kind == "allowed_products" and "groceries" in r.params.get("products", []) for r in rules)
        if not (covered and groceries and "groceries" in (beneficiary.allowed_products or [])):
            continue
        ids = {str(i) for r in rules if r.kind == "allowed_payees" for i in r.params.get("payee_ids", [])}
        stores = [p for p in Payee.objects.filter(pk__in=ids, verified=True)
                  if (p.catalogue or {}).get("items") and (not p.products or "groceries" in p.products)]
        if stores:
            result.append((m, stores))
    return result


@transaction.atomic
def set_shop_link(family, beneficiary, user, enabled, new=False):
    """A funder gets the beneficiary's shop link (the active one, or a new secret) or turns it off."""
    from .models import ShopLink

    require_funder(user, family)
    if beneficiary.family_id != family.id:
        raise ServiceError("That person belongs to another family")
    current = ShopLink.objects.select_for_update().filter(beneficiary=beneficiary, active=True).first()
    if enabled and current is not None and not new:
        return current
    ShopLink.objects.filter(beneficiary=beneficiary, active=True).update(active=False)
    if not enabled:
        return None
    if not shop_mandates(family, beneficiary):
        raise ServiceError(f"No mandate covers groceries for {beneficiary.name} from a store with a price list")
    return ShopLink.objects.create(family=family, beneficiary=beneficiary, token=secrets.token_urlsafe(16),
                                   created_by=user)


def active_shop_link(token):
    from .models import ShopLink

    link = ShopLink.objects.filter(token=token, active=True).select_related("family", "beneficiary").first() \
        if token else None
    if link is None:
        raise ServiceError("This shop link is not active")
    return link


def place_shop_order(link, *, mandate_id, store_id, lines, fulfilment, ask="all", note="", idempotency_key="",
                     intent_analyzer=None, now=None):
    """The beneficiary sends a shopping list. Paid from the fund when the rules allow; when the fund is short
    (and only then), it becomes an invoice to every funder or the one they chose."""
    from datetime import timedelta

    from agent import policy

    beneficiary = link.beneficiary
    key = f"shop-{link.id}-{idempotency_key or secrets.token_hex(8)}"[:100]
    if existing := Request.objects.filter(idempotency_key=key).first():
        return existing
    found = next(((m, s) for m, s in shop_mandates(link.family, beneficiary) if str(m.id) == str(mandate_id)), None)
    if found is None:
        raise ServiceError("Choose which support this shopping is from")
    mandate, stores = found
    store = next((s for s in stores if str(s.id) == str(store_id)), stores[0] if len(stores) == 1 else None)
    if store is None:
        raise ServiceError("Choose a store")
    funders = {str(f.user_id): f.user for f in mandate.mandate_funders.select_related("user")}
    if ask not in ("all", None, "") and str(ask) not in funders:
        raise ServiceError("Choose who to ask")
    since = (now or timezone.now()) - timedelta(hours=24)
    if Request.objects.filter(channel=Request.SHOP, beneficiary=beneficiary, created_at__gte=since).count() \
            >= SHOP_ORDERS_PER_DAY:
        raise ServiceError("Too many shopping lists today. Try again tomorrow or call the family")
    amount, details = grocery_items_order(store, lines, fulfilment, beneficiary)
    request = submit_request(
        mandate=mandate, amount=amount, product="groceries", payee=store, beneficiary=beneficiary,
        channel=Request.SHOP, requester_phone=beneficiary.phone, requester_display=beneficiary.name,
        message_text=(note or "").strip()[:500], fulfilment=fulfilment, details=details,
        summary_en=f"{beneficiary.name} sent a shopping list from {store.name}", idempotency_key=key,
        intent_analyzer=intent_analyzer, now=now)
    if request.status == Request.REFUSED and policy.funds_short(request):
        _fund_short(request, funders.get(str(ask)) if ask not in ("all", None, "") else None, now)
    request.refresh_from_db()
    return request


@transaction.atomic
def _fund_short(request, ask_user, now=None):
    """The fund can't cover a shopping list. If it would pass with the money there, send it to the funders to pay;
    a fraud hold still holds, and any other broken rule stays a refusal."""
    from agent import policy

    lock_mandate(request.mandate)
    request = Request.objects.select_for_update().get(pk=request.pk)
    result = policy.check(request, now, ignore_balance=True)
    if result.outcome == Decision.HOLD_FRAUD:
        status, reason = Request.HELD_FRAUD, result.reason
    elif result.outcome == Decision.REFUSE:
        status, reason = Request.REFUSED, result.reason
    else:
        status = Request.INVOICED
        who = _name(ask_user) if ask_user else "everyone"
        reason = f"The support fund can't cover this right now, so it was sent to {who} to pay with PayPal"
    Decision.objects.create(request=request, outcome=Decision.ESCALATE if status == Request.INVOICED else
                            result.outcome, reason=reason, rule_results=result.rule_results, decided_by=Decision.POLICY)
    request.status = status
    request.invoice_to = ask_user if status == Request.INVOICED else None
    request.save(update_fields=["status", "invoice_to", "updated_at"])
    record(request.mandate, LedgerEntry.INVOICED if status == Request.INVOICED else LedgerEntry.DECIDED, "POLICY",
           request=request, amount=request.amount, reason=reason,
           **({"invoice_to": ask_user.pk} if ask_user else {}))
    if status == Request.INVOICED:
        notify(_addressed(request), f"{_whose(request).capitalize()} shopping list from {request.payee.name} "
                                    f"(${request.amount:.2f}) needs paying: the support fund is short.", request)
    else:
        execute_decision(request)


def check_invoice_payable(request, user):
    """Before a funder pays a shopping list: is it still open, sent to them, and within every hard rule?"""
    from agent import policy

    if request.status != Request.INVOICED:
        raise ServiceError("This shopping list is no longer waiting to be paid")
    if not request.mandate.mandate_funders.filter(user=user).exists() or \
            request.invoice_to_id not in (None, user.pk):
        raise ServiceError("This shopping list was sent to someone else")
    result = policy.check(request, funder_verified=True, ignore_balance=True)
    if result.outcome != Decision.APPROVE:
        raise ServiceError(result.reason)


def settle_invoice(funding):
    """Called once when a funder's PayPal payment for a shopping list is captured (inside that transaction).
    The first payment decides and pays the list; a second, late payment simply stays in the fund."""
    from agent import policy

    lock_mandate(funding.mandate)
    request = Request.objects.select_for_update().get(pk=funding.for_request_id)
    payer = funding.funder
    if request.status != Request.INVOICED:
        notify([payer], f"{_whose(request).capitalize()} shopping list was already covered, so your "
                        f"${funding.amount:.2f} was added to {request.mandate.title}.", request)
        return request
    actor = actor_of(payer)
    result = policy.check(request, funder_verified=True)
    Decision.objects.create(request=request, outcome=result.outcome, reason=(
        f"Paid by {_name(payer)} with PayPal; all rules passed" if result.outcome == Decision.APPROVE else result.reason),
        rule_results=result.rule_results, decided_by=actor)
    request.status = Request.APPROVED if result.outcome == Decision.APPROVE else Request.REFUSED
    request.details = {**request.details, "paid_by": _name(payer)}
    request.save(update_fields=["status", "details", "updated_at"])
    record(request.mandate, LedgerEntry.DECIDED, actor, request=request, amount=request.amount,
           outcome=result.outcome, reason=result.reason, paid_by=payer.pk)
    if request.status == Request.APPROVED:
        notify(_others(request, payer), f"{_name(payer)} paid {_whose(request)} shopping list "
                                        f"(${request.amount:.2f}). Nothing for you to do.", request)
        notify([payer], f"Thank you. {_whose(request).capitalize()} shopping list is paid.", request)
        execute_decision(request)
    else:
        notify([payer], f"{_whose(request).capitalize()} shopping list could not be paid ({result.reason}); "
                        f"your ${funding.amount:.2f} is in {request.mandate.title}.", request)
    return request
