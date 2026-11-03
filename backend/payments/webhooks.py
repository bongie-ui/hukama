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

from .models import RailTransaction, WebhookEvent
from .paypal_client import PayPalError, get_client
from .payouts import apply_rail_status

WEBHOOK_PATH = "/api/webhooks/paypal/"
EVENT_TYPES = ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED", "PAYMENT.PAYOUTSBATCH.SUCCESS",
               "PAYMENT.PAYOUTSBATCH.DENIED", "PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTS-ITEM.FAILED",
               "PAYMENT.PAYOUTS-ITEM.RETURNED", "PAYMENT.PAYOUTS-ITEM.BLOCKED", "PAYMENT.PAYOUTS-ITEM.DENIED")
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
    try:
        with transaction.atomic():
            stored = WebhookEvent.objects.create(paypal_event_id=event["id"], event_type=event.get("event_type", ""),
                                                 payload=event)
    except IntegrityError:
        return "duplicate"
    handled = apply(event)
    stored.processed_at = timezone.now()
    stored.save(update_fields=["processed_at", "updated_at"])
    return "processed" if handled else "ignored"


def apply(event):
    kind, resource = event.get("event_type", ""), event.get("resource") or {}
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        return _capture_completed(resource)
    if kind == "PAYMENT.CAPTURE.DENIED":
        return _capture_denied(resource)
    if kind.startswith("PAYMENT.PAYOUTSBATCH."):
        return _payout(resource.get("batch_header", {}).get("payout_batch_id"),
                       resource.get("batch_header", {}).get("batch_status"), event)
    if kind.startswith("PAYMENT.PAYOUTS-ITEM."):
        return _payout(resource.get("payout_batch_id"), resource.get("transaction_status"), event)
    return False


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


_PAYOUT_STATUS = {"SUCCESS": RailTransaction.SUCCESS, "SUCCEEDED": RailTransaction.SUCCESS,
                  "FAILED": RailTransaction.FAILED, "DENIED": RailTransaction.FAILED,
                  "BLOCKED": RailTransaction.FAILED, "RETURNED": RailTransaction.RETURNED}


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
            return hook["id"]
    created = client.request("POST", "/v1/notifications/webhooks", json={
        "url": url, "event_types": [{"name": name} for name in EVENT_TYPES]})
    return created["id"]
