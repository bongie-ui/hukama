"""PayPal webhooks (BUILD_SPEC §12): verified, stored once, applied idempotently.

Every event is checked with PayPal's verify-webhook-signature API before anything changes. Events are
deduplicated by PayPal's event id. Handlers only move state forward through the same functions polling uses
(apply_rail_status, mark_funding_captured), so a webhook, a poll and a retry can never double-count.
"""

from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from mandates import services
from mandates.models import Funding

from . import premiums
from .models import PremiumSubscription, RailTransaction, WebhookEvent
from .paypal_client import PayPalError, get_client
from .payouts import apply_rail_status

WEBHOOK_PATH = "/api/webhooks/paypal/"
EVENT_TYPES = ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.PAYOUTSBATCH.SUCCESS",
               "PAYMENT.PAYOUTSBATCH.DENIED", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTS-ITEM.FAILED",
               "PAYMENT.PAYOUTS-ITEM.RETURNED", "PAYMENT.PAYOUTS-ITEM.BLOCKED", "PAYMENT.PAYOUTS-ITEM.DENIED",
               "BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED",
               "BILLING.SUBSCRIPTION.EXPIRED", "PAYMENT.SALE.COMPLETED", "PAYMENT.CAPTURE.REFUNDED",
               "PAYMENT.CAPTURE.REVERSED")
HEADERS = {"auth_algo": "PAYPAL-AUTH-ALGO", "cert_url": "PAYPAL-CERT-URL", "transmission_id": "PAYPAL-TRANSMISSION-ID",
           "transmission_sig": "PAYPAL-TRANSMISSION-SIG", "transmission_time": "PAYPAL-TRANSMISSION-TIME"}


class WebhookError(Exception):
    pass


_webhook_id = None


def webhook_id(client=None):
    """PAYPAL_WEBHOOK_ID, or the id of this app's webhook pointing at our URL (looked up once)."""
    global _webhook_id
    if settings.PAYPAL_WEBHOOK_ID:
        return settings.PAYPAL_WEBHOOK_ID
    if _webhook_id is None:
        hooks = (client or get_client()).request("GET", "/v1/notifications/webhooks").get("webhooks", [])
        _webhook_id = next((h["id"] for h in hooks if h.get("url", "").endswith(WEBHOOK_PATH)), "")
    return _webhook_id


def verify(headers, event, client=None):
    """True only when PayPal confirms this exact event was signed for our webhook."""
    client = client or get_client()
    hook = webhook_id(client)
    values = {key: headers.get(header, "") for key, header in HEADERS.items()}
    if not hook or not all(values.values()):
        return False
    try:
        result = client.request("POST", "/v1/notifications/verify-webhook-signature",
                                json={**values, "webhook_id": hook, "webhook_event": event})
    except PayPalError:
        return False
    return result.get("verification_status") == "SUCCESS"


def receive(headers, event, client=None):
    """Verify, store once, apply. Returns "processed", "duplicate" or "ignored"."""
    if not isinstance(event, dict) or not event.get("id"):
        raise WebhookError("Not a PayPal event")
    if not verify(headers, event, client):
        raise WebhookError("Signature could not be verified")
    # Store and apply in one transaction: if applying fails, the event is not kept as seen, PayPal retries it,
    # and the retry is applied instead of being dropped as a duplicate.
    try:
        with transaction.atomic():
            stored = WebhookEvent.objects.create(paypal_event_id=event["id"], event_type=event.get("event_type", ""),
                                                 payload=event)
            handled = apply(event)
            stored.processed_at = timezone.now()
            stored.save(update_fields=["processed_at", "updated_at"])
    except IntegrityError:
        if WebhookEvent.objects.filter(paypal_event_id=event["id"]).exists():
            return "duplicate"
        raise
    return "processed" if handled else "ignored"


def apply(event):
    kind, resource = event.get("event_type", ""), event.get("resource") or {}
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        return _capture_completed(resource)
    if kind == "PAYMENT.CAPTURE.DENIED":
        return _capture_denied(resource)
    if kind in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        return _capture_returned(resource, reversed_=kind.endswith("REVERSED"))
    if kind.startswith("PAYMENT.PAYOUTSBATCH."):
        return _payout(resource.get("batch_header", {}).get("payout_batch_id"),
                       resource.get("batch_header", {}).get("batch_status"), event)
    if kind.startswith("PAYMENT.PAYOUTS-ITEM."):
        return _payout(resource.get("payout_batch_id"), resource.get("transaction_status"), event)
    if kind.startswith("BILLING.SUBSCRIPTION."):
        premium = _premium(resource.get("id"))
        return bool(premium and premiums.set_status(premium, resource.get("status") or kind.rsplit(".", 1)[1]))
    if kind == "PAYMENT.SALE.COMPLETED":
        premium = _premium(resource.get("billing_agreement_id"))
        if premium is None:
            return False
        premiums.record_payment(premium, resource.get("id"), (resource.get("amount") or {}).get("total", "0"))
        return True
    return False


def _premium(subscription_id):
    return PremiumSubscription.objects.filter(paypal_subscription_id=subscription_id).first() \
        if subscription_id else None


def _funding_for(resource):
    funding = Funding.objects.filter(pk=resource.get("custom_id")).select_related("mandate").first() \
        if resource.get("custom_id") else None
    if funding is None:
        order_id = (resource.get("supplementary_data") or {}).get("related_ids", {}).get("order_id")
        funding = Funding.objects.filter(paypal_order_id=order_id).select_related("mandate").first() if order_id else None
    return funding


def _capture_completed(resource):
    funding = _funding_for(resource)
    amount = resource.get("amount") or {}
    if funding is None or amount.get("currency_code") != funding.mandate.currency or \
            Decimal(str(amount.get("value", "0"))) != funding.amount:
        return False
    services.mark_funding_captured(funding, external_id=resource.get("id"))  # idempotent
    return True


def _capture_denied(resource):
    funding = _funding_for(resource)
    if funding is None or funding.status != Funding.CREATED:
        return False
    funding.status, funding.failure_reason = Funding.FAILED, "PayPal denied the payment"
    funding.save(update_fields=["status", "failure_reason", "updated_at"])
    return True


def _capture_id(resource):
    """The capture a refund belongs to: its HATEOAS "up" link ends with the capture id."""
    for link in resource.get("links") or []:
        if link.get("rel") == "up" and "/captures/" in link.get("href", ""):
            return link["href"].rstrip("/").rsplit("/", 1)[-1]
    return None


def _capture_returned(resource, reversed_):
    """A refund or chargeback: that money no longer counts towards the mandate (captured_total drops)."""
    if reversed_:  # the resource is the capture itself
        funding = _funding_for(resource) or Funding.objects.filter(external_id=resource.get("id") or "-").first()
    else:
        capture_id = _capture_id(resource)
        funding = _funding_for(resource) or (Funding.objects.filter(external_id=capture_id).first()
                                             if capture_id else None)
    if funding is None:
        return False
    if reversed_:
        refunded = funding.amount
    else:
        total = ((resource.get("seller_payable_breakdown") or {}).get("total_refunded_amount") or {}).get("value")
        value = total if total is not None else (resource.get("amount") or {}).get("value", "0")
        refunded = Decimal(str(value)) if total is not None else funding.refunded + Decimal(str(value))
    services.record_refund(funding, refunded, refund_id=resource.get("id", ""), chargeback=reversed_)
    return True


_PAYOUT_STATUS = {"SUCCESS": RailTransaction.SUCCESS, "SUCCEEDED": RailTransaction.SUCCESS,
                  "FAILED": RailTransaction.FAILED, "DENIED": RailTransaction.FAILED,
                  "BLOCKED": RailTransaction.FAILED, "RETURNED": RailTransaction.RETURNED,
                  "REFUNDED": RailTransaction.RETURNED, "REVERSED": RailTransaction.RETURNED}


def _payout(batch_id, status, event):
    tx = RailTransaction.objects.filter(external_id=batch_id, simulated=False).first() if batch_id else None
    new = _PAYOUT_STATUS.get((status or "").upper())
    if tx is None or new is None:
        return False
    apply_rail_status(tx, new, raw={"webhook": event.get("event_type"), "event_id": event.get("id")})
    return True


def register(url, client=None):
    """Create (or find) this app's webhook for `url` with the events we handle. Returns its id."""
    client = client or get_client()
    for hook in client.request("GET", "/v1/notifications/webhooks").get("webhooks", []):
        if hook.get("url") == url:
            if {e["name"] for e in hook.get("event_types", [])} != set(EVENT_TYPES):
                client.request("PATCH", f"/v1/notifications/webhooks/{hook['id']}", json=[
                    {"op": "replace", "path": "/event_types", "value": [{"name": n} for n in EVENT_TYPES]}])
            return hook["id"]
    created = client.request("POST", "/v1/notifications/webhooks", json={
        "url": url, "event_types": [{"name": name} for name in EVENT_TYPES]})
    return created["id"]
