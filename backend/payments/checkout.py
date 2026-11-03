"""REAL: money into a mandate through PayPal checkout (Orders v2), via the APIMatic-generated PayPal Server SDK.

Built with the APIMatic Context Plugin for PayPal. The browser shows the PayPal button (JS SDK v6); this module
creates the order on the server and captures it after the payer approves. A Funding row exists from order
creation (CREATED) and only becomes CAPTURED after PayPal confirms the capture for exactly the amount we asked
for, against our own funding id. Both calls carry a PayPal-Request-Id, so a retry can never charge twice.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from mandates import services
from mandates.models import Funding

MAX_AMOUNT = Decimal("5000")


class CheckoutError(Exception):
    """PayPal could not complete the step; the message is safe to show."""


def is_configured():
    return bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET)


def is_sandbox():
    return "sandbox" in settings.PAYPAL_BASE_URL


def _orders():
    from paypalserversdk.configuration import Environment
    from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
    from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

    client = PaypalServersdkClient(
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.PAYPAL_CLIENT_ID, o_auth_client_secret=settings.PAYPAL_CLIENT_SECRET),
        environment=Environment.SANDBOX if is_sandbox() else Environment.PRODUCTION,
        timeout=20, max_retries=2)
    return client.orders


def _call(method, request):
    """Run an Orders call; turn SDK errors into a CheckoutError carrying PayPal's issue codes."""
    from paypalserversdk.exceptions.api_exception import ApiException
    from paypalserversdk.exceptions.error_exception import ErrorException

    try:
        result = method(request)
    except ErrorException as exc:
        issues = [d.issue for d in (exc.details or []) if getattr(d, "issue", None)]
        error = CheckoutError(exc.message or "PayPal refused the request")
        error.issues = issues
        raise error from exc
    except ApiException as exc:
        raise CheckoutError(f"PayPal is unreachable right now ({exc.response_code})") from exc
    if not result.is_success():
        raise CheckoutError("PayPal refused the request")
    return result.body


def validate_amount(amount):
    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (ArithmeticError, ValueError):
        raise services.ServiceError("Enter an amount in dollars")
    if amount <= 0 or amount > MAX_AMOUNT:
        raise services.ServiceError(f"Enter an amount between $1 and ${MAX_AMOUNT:,.0f}")
    return amount


def start(mandate, amount, *, funder=None, contributor_name="", message="", orders=None):
    """Create a Funding and its PayPal order. Returns the Funding (its paypal_order_id goes to the button)."""
    from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
    from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
    from paypalserversdk.models.order_request import OrderRequest
    from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest

    if not is_configured():
        raise CheckoutError("PayPal is not configured on this server")
    amount = validate_amount(amount)
    funding = services.create_funding(mandate, funder, amount)
    funding.contributor_name, funding.message = contributor_name.strip()[:120], message.strip()[:200]
    order = _call((orders or _orders()).create_order, {
        "body": OrderRequest(intent=CheckoutPaymentIntent.CAPTURE, purchase_units=[PurchaseUnitRequest(
            reference_id=f"hukama-{mandate.id}", custom_id=str(funding.id),
            description=f"Hukama: {mandate.title}"[:127],
            amount=AmountWithBreakdown(currency_code=mandate.currency, value=f"{amount:.2f}"))]),
        "paypal_request_id": f"hukama-order-{funding.id}",
        "prefer": "return=minimal",
    })
    funding.paypal_order_id = order.id
    funding.save(update_fields=["contributor_name", "message", "paypal_order_id", "updated_at"])
    return funding


def _completed_capture(order, funding):
    """The completed capture in `order` for exactly this funding and amount, else None."""
    for unit in order.purchase_units or []:
        for capture in getattr(getattr(unit, "payments", None), "captures", None) or []:
            if capture.status != "COMPLETED" or capture.custom_id not in (None, str(funding.id)):
                continue
            if capture.amount.currency_code == funding.mandate.currency and \
                    Decimal(capture.amount.value) == funding.amount:
                return capture
    return None


def finish(funding, *, orders=None):
    """Capture the approved order and record the money. Safe to call twice (returns the captured Funding)."""
    funding, failure = _finish(funding, orders or _orders())
    if failure:  # raised after the transaction commits, so the FAILED status and reason are kept
        raise CheckoutError(failure)
    return funding


@transaction.atomic
def _finish(funding, orders):
    funding = Funding.objects.select_for_update().select_related("mandate").get(pk=funding.pk)
    if funding.status == Funding.CAPTURED:
        return funding, None
    try:
        order = _call(orders.capture_order, {"id": funding.paypal_order_id,
                                             "paypal_request_id": f"hukama-capture-{funding.id}",
                                             "prefer": "return=representation"})
    except CheckoutError as exc:
        if "ORDER_ALREADY_CAPTURED" not in getattr(exc, "issues", []):
            raise
        order = _call(orders.get_order, {"id": funding.paypal_order_id})  # captured elsewhere: reconcile
    capture = _completed_capture(order, funding)
    if capture is None:
        funding.status, funding.failure_reason = Funding.FAILED, f"PayPal order {order.status}, no matching capture"
        funding.save(update_fields=["status", "failure_reason", "updated_at"])
        return funding, "The payment was not completed. Nothing was taken."
    return services.mark_funding_captured(funding, external_id=capture.id), None
