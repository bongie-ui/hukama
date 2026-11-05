"""REAL: monthly premiums (funeral cover, medical aid) through PayPal Subscriptions.

Built with the APIMatic Context Plugin for PayPal. The billing plan, the subscription, its transactions and
cancellation go through the PayPal Server SDK (`client.subscriptions`). Two gaps in the SDK use PayPal's REST
API through our client: creating the catalog product a plan needs, and reading a subscription's status
(the SDK's Subscription model has no status field).

Money flow: each premium PayPal collects is recorded as Funding for the mandate (once per PayPal transaction
id), then paid to the cover provider as a scheduled Request through the policy engine, like any payment.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from mandates import services
from mandates.models import Funding, LedgerEntry, Request
from mandates.templates import PAYPAL_SUBSCRIPTIONS, TEMPLATES

from .checkout import CheckoutError, call, is_configured, sdk
from .models import PayPalPlan, PremiumSubscription
from .paypal_client import PayPalError, get_client

PRODUCT_NAME = "Hukama family cover"


def premium_for(mandate):
    """The monthly premium: the mandate's per-payment limit. None when the mandate takes no premiums."""
    if PAYPAL_SUBSCRIPTIONS not in TEMPLATES[mandate.type].funding:
        return None
    rule = next((r for r in mandate.rules.all() if r.kind == "max_per_request"), None)
    return Decimal(str(rule.params["amount"])).quantize(Decimal("0.01")) if rule else None


def ensure_plan(amount, currency="USD", subscriptions=None, client=None):
    """A monthly billing plan at `amount`, created once and reused."""
    from paypalserversdk.models.frequency import Frequency
    from paypalserversdk.models.interval_unit import IntervalUnit
    from paypalserversdk.models.money import Money
    from paypalserversdk.models.payment_preferences import PaymentPreferences
    from paypalserversdk.models.plan_request import PlanRequest
    from paypalserversdk.models.plan_request_status import PlanRequestStatus
    from paypalserversdk.models.setup_fee_failure_action import SetupFeeFailureAction
    from paypalserversdk.models.subscription_billing_cycle import SubscriptionBillingCycle
    from paypalserversdk.models.subscription_pricing_scheme import SubscriptionPricingScheme
    from paypalserversdk.models.tenure_type import TenureType

    existing = PayPalPlan.objects.filter(amount=amount, currency=currency).first()
    if existing:
        return existing
    product = _product(client or get_client())
    plan = call((subscriptions or sdk().subscriptions).create_billing_plan, {
        "prefer": "return=representation",
        "body": PlanRequest(
            product_id=product, name=f"Monthly premium {currency} {amount:.2f}",
            billing_cycles=[SubscriptionBillingCycle(
                frequency=Frequency(interval_unit=IntervalUnit.MONTH, interval_count=1),
                tenure_type=TenureType.REGULAR, sequence=1, total_cycles=0,
                pricing_scheme=SubscriptionPricingScheme(fixed_price=Money(currency_code=currency,
                                                                           value=f"{amount:.2f}")))],
            payment_preferences=PaymentPreferences(auto_bill_outstanding=True, payment_failure_threshold=1,
                                                   setup_fee_failure_action=SetupFeeFailureAction.CANCEL),
            status=PlanRequestStatus.ACTIVE, quantity_supported=False),
    })
    return PayPalPlan.objects.create(name=plan.name or PRODUCT_NAME, product_id=product, plan_id=plan.id,
                                     amount=amount, currency=currency)


def _product(client):
    """The catalog product all premium plans belong to (Catalog Products REST API; not in the SDK)."""
    known = PayPalPlan.objects.values_list("product_id", flat=True).first()
    if known:
        return known
    try:
        created = client.request("POST", "/v1/catalogs/products", json={
            "name": PRODUCT_NAME, "type": "SERVICE", "category": "INSURANCE_DIRECT",
            "description": "Monthly cover premiums paid through Hukama"},
            headers={"PayPal-Request-Id": "hukama-cover-product"})
    except PayPalError as exc:
        raise CheckoutError(f"Could not set up the premium with PayPal ({exc})") from exc
    return created["id"]


def start(mandate, funder, return_base, subscriptions=None, client=None):
    """Create the PayPal subscription; returns (PremiumSubscription, approve_url) for the funder to approve."""
    from paypalserversdk.models.create_subscription_request import CreateSubscriptionRequest
    from paypalserversdk.models.subscription_application_context import SubscriptionApplicationContext

    if not is_configured():
        raise CheckoutError("PayPal is not configured on this server")
    if not mandate.mandate_funders.filter(user=funder).exists():
        raise services.ServiceError("Only this mandate's funders can pay its premium")
    amount = premium_for(mandate)
    if amount is None:
        raise services.ServiceError("This mandate does not take monthly premiums")
    if mandate.premium_subscriptions.filter(status=PremiumSubscription.ACTIVE).exists():
        raise services.ServiceError("A monthly premium is already active for this cover")
    subscriptions = subscriptions or sdk().subscriptions
    plan = ensure_plan(amount, mandate.currency, subscriptions, client)
    premium = PremiumSubscription.objects.create(mandate=mandate, funder=funder, plan=plan, amount=amount)
    back = f"{return_base.rstrip('/')}/paypal/premium-return/?premium={premium.id}"
    created = call(subscriptions.create_subscription, {
        "prefer": "return=representation",
        "body": CreateSubscriptionRequest(
            plan_id=plan.plan_id, custom_id=str(premium.id), auto_renewal=True,
            application_context=SubscriptionApplicationContext(return_url=back, cancel_url=f"{back}&cancelled=1")),
    })
    premium.paypal_subscription_id = created.id
    premium.save(update_fields=["paypal_subscription_id", "updated_at"])
    _record(premium, str(funder.pk))
    approve = next((link.href for link in created.links or [] if link.rel == "approve"), None)
    if not approve:
        raise CheckoutError("PayPal did not return an approval link")
    return premium, approve


def _record(premium, actor):
    services.record(premium.mandate, LedgerEntry.PREMIUM_CHANGED, actor, amount=premium.amount,
                    status=premium.status, subscription=premium.paypal_subscription_id)


def set_status(premium, status, actor="PAYPAL"):
    status = (status or "").upper()
    if status not in dict(PremiumSubscription.STATUSES) or status == premium.status:
        return premium
    premium.status = status
    if status == PremiumSubscription.ACTIVE and not premium.activated_at:
        premium.activated_at = timezone.now()
    if status in (PremiumSubscription.CANCELLED, PremiumSubscription.EXPIRED):
        premium.cancelled_at = premium.cancelled_at or timezone.now()
    premium.save(update_fields=["status", "activated_at", "cancelled_at", "updated_at"])
    _record(premium, actor)
    return premium


def sync(premium, subscriptions=None, client=None):
    """Bring status and payments up to date from PayPal (used after approval and when webhooks are absent)."""
    if not premium.paypal_subscription_id:
        return premium
    try:
        data = (client or get_client()).request("GET", f"/v1/billing/subscriptions/{premium.paypal_subscription_id}")
    except PayPalError as exc:
        raise CheckoutError("PayPal could not be reached to check the premium") from exc
    set_status(premium, data.get("status"))
    if premium.status in (PremiumSubscription.ACTIVE, PremiumSubscription.CANCELLED, PremiumSubscription.SUSPENDED):
        now = timezone.now()
        listed = call((subscriptions or sdk().subscriptions).list_subscription_transactions, {
            "id": premium.paypal_subscription_id,
            "start_time": (premium.created_at - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")})
        for txn in listed.transactions or []:
            if str(txn.status).upper() == "COMPLETED":
                record_payment(premium, txn.id, txn.amount_with_breakdown.gross_amount.value)
    return premium


@transaction.atomic
def record_payment(premium, transaction_id, amount):
    """One PayPal premium payment: fund the mandate once, then pay the provider through the rules.
    Returns the premium Request, or None when this payment was already recorded or does not match."""
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    # A webhook and a sync can report the same payment at once: one at a time per premium.
    premium = PremiumSubscription.objects.select_for_update().select_related("mandate", "funder").get(pk=premium.pk)
    if amount != premium.amount or Funding.objects.filter(external_id=transaction_id).exists():
        return None
    mandate = premium.mandate
    funding = services.create_funding(mandate, premium.funder, amount, external_id=transaction_id)
    services.mark_funding_captured(funding, external_id=transaction_id)
    if premium.status == PremiumSubscription.APPROVAL_PENDING:
        set_status(premium, PremiumSubscription.ACTIVE)
    return services.submit_request(
        mandate=mandate, amount=amount, product="premium", payee=services.sole_payee(mandate, "premium"),
        channel=Request.SCHEDULE, requester_user=premium.funder, requester_display="Monthly premium",
        message_text=f"Monthly premium for {mandate.title}", idempotency_key=f"premium-{transaction_id}")


def cancel(premium, user, subscriptions=None):
    from paypalserversdk.models.cancel_subscription_request import CancelSubscriptionRequest

    if not premium.mandate.mandate_funders.filter(user=user).exists():
        raise services.ServiceError("Only this mandate's funders can stop its premium")
    if premium.status in (PremiumSubscription.CANCELLED, PremiumSubscription.EXPIRED):
        return premium
    if premium.paypal_subscription_id and premium.status != PremiumSubscription.APPROVAL_PENDING:
        call((subscriptions or sdk().subscriptions).cancel_subscription, {
            "id": premium.paypal_subscription_id,
            "body": CancelSubscriptionRequest(reason="Stopped by a family funder in Hukama")})
    return set_status(premium, PremiumSubscription.CANCELLED, actor=str(user.pk))


def public_base(request):
    """Where PayPal sends the funder back: this site (Render's host in production)."""
    return settings.PUBLIC_BASE_URL or request.build_absolute_uri("/")
