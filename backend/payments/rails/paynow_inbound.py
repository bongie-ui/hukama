"""REAL (test mode): local relatives contribute to a pool from their mobile money wallet via Paynow.

Inbound only: money comes into a mandate, never out. The relative approves the payment on their own
phone; we poll (or receive Paynow's result callback) and capture the Funding once it is paid.

Protocol: form-encoded POSTs signed with an uppercase SHA-512 hash of the field values (in order) plus the
integration key. Test mode accepts the merchant's own email as `authemail`, and the documented test
numbers: 0771111111 succeeds, 0772222222 succeeds after a delay, 0773333333 is cancelled by the user,
0774444444 fails for insufficient balance.
"""

import hashlib
from decimal import Decimal
from urllib.parse import parse_qsl

import requests
from django.conf import settings

from core.phones import normalize_phone
from mandates import services
from mandates.models import Funding, LedgerEntry

INITIATE_URL = "https://www.paynow.co.zw/interface/remotetransaction"
TIMEOUT_SECONDS = 20
# Paynow's statuses that mean the money arrived, and those that mean it never will.
PAID = {"paid", "awaiting delivery", "delivered"}
DEAD = {"cancelled", "failed", "disputed", "refunded"}
# Wallet method: Paynow's parameter value for the main local mobile money network (not shown to users).
METHOD = "ecocash"


class PaynowError(Exception):
    pass


def is_configured():
    return bool(settings.PAYNOW_INTEGRATION_ID and settings.PAYNOW_INTEGRATION_KEY and settings.PAYNOW_AUTH_EMAIL)


def make_hash(values, key):
    """SHA-512 over every value in order (the hash field itself excluded), then the integration key."""
    text = "".join(str(v) for k, v in values if k.lower() != "hash") + key
    return hashlib.sha512(text.encode("utf-8")).hexdigest().upper()


def parse(body, key):
    """Parse a form-encoded Paynow reply and check its hash. Returns a dict with lower-cased keys."""
    pairs = parse_qsl(body, keep_blank_values=True)
    data = {k.lower(): v for k, v in pairs}
    if data.get("status", "").lower() == "error":
        raise PaynowError(data.get("error") or "Paynow refused the payment")
    if data.get("hash") != make_hash(pairs, key):
        raise PaynowError("Paynow reply failed the hash check")
    return data


def _post(url, fields=None, session=None):
    try:
        response = (session or requests).post(url, data=fields or {}, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise PaynowError(f"Paynow unreachable: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise PaynowError(f"Paynow answered HTTP {response.status_code}")
    return response.text


def start_contribution(*, mandate, amount, name, phone, started_by=None, session=None):
    """Ask Paynow to push a payment prompt to the relative's phone. Returns (Funding, instructions)."""
    if not is_configured():
        raise services.ServiceError("Local mobile money contributions are not switched on yet")
    e164 = normalize_phone(phone)
    if not e164 or not name.strip():
        raise services.ServiceError("Enter the relative's name and a valid phone number")
    funding = services.create_funding(mandate, None, Decimal(amount), rail=Funding.PAYNOW_INBOUND)
    funding.contributor_name, funding.contributor_phone = name.strip()[:120], e164
    local = "0" + e164[4:] if e164.startswith("+263") else e164  # Paynow expects the local format
    fields = [
        ("resulturl", settings.PAYNOW_RESULT_URL), ("returnurl", settings.PAYNOW_RETURN_URL),
        ("reference", f"hukama-{funding.id}"), ("amount", f"{funding.amount:.2f}"),
        ("id", settings.PAYNOW_INTEGRATION_ID), ("additionalinfo", f"{mandate.title} - {funding.contributor_name}"[:200]),
        ("authemail", settings.PAYNOW_AUTH_EMAIL), ("phone", local), ("method", METHOD), ("status", "Message"),
    ]
    fields.append(("hash", make_hash(fields, settings.PAYNOW_INTEGRATION_KEY)))
    try:
        data = parse(_post(INITIATE_URL, fields, session), settings.PAYNOW_INTEGRATION_KEY)
    except PaynowError as exc:
        funding.status, funding.failure_reason = Funding.FAILED, str(exc)[:200]
        funding.save()
        raise services.ServiceError(f"The payment could not be started: {exc}")
    funding.poll_url = data.get("pollurl", "")
    funding.external_id = data.get("paynowreference", "")[:64]
    funding.save()
    return funding, data.get("instructions", "")


def check_contribution(funding, session=None):
    """Ask Paynow for the latest status; capture on paid, fail on cancelled. Idempotent."""
    if funding.status != Funding.CREATED or not funding.poll_url:
        return funding
    data = parse(_post(funding.poll_url, session=session), settings.PAYNOW_INTEGRATION_KEY)
    return apply_status(funding, data)


def apply_status(funding, data):
    """Apply a verified Paynow status (from polling or the result callback)."""
    status = data.get("status", "").lower()
    if status in PAID:
        if Decimal(data.get("amount") or funding.amount) != funding.amount:
            raise PaynowError("Paid amount does not match the contribution")
        funding = services.mark_funding_captured(funding, external_id=data.get("paynowreference") or None)
    elif status in DEAD and funding.status == Funding.CREATED:
        funding.status, funding.failure_reason = Funding.FAILED, f"Payment {status} on the phone"
        funding.save(update_fields=["status", "failure_reason", "updated_at"])
        services.record(funding.mandate, LedgerEntry.FAILED, f"Local: {funding.contributor_name}",
                        amount=funding.amount, funding_id=str(funding.id), rail=funding.rail, status=status)
    return funding


def handle_result(body):
    """Paynow's server-to-server result callback: verify, find the funding by our reference, apply."""
    data = parse(body, settings.PAYNOW_INTEGRATION_KEY)
    reference = data.get("reference", "")
    if not reference.startswith("hukama-"):
        raise PaynowError("Unknown reference")
    funding = Funding.objects.filter(pk=reference.removeprefix("hukama-"), rail=Funding.PAYNOW_INBOUND).first()
    if funding is None:
        raise PaynowError("Unknown contribution")
    return apply_status(funding, data)
