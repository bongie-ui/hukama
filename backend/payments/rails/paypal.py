"""REAL rails on PayPal Payouts (sandbox): suppliers, schools and grocers are paid directly, and the local
mobile money provider is paid for what it then delivers to the beneficiary's phone."""

from decimal import Decimal

from payments.paypal_client import PayPalError, get_client

from .base import Payee, Rail, RailError, RailResult, RailStatus, validate_amount

# PayPal batch_status values mapped onto our three-state flow.
_STATUS_MAP = {
    "PENDING": RailStatus.PENDING,
    "PROCESSING": RailStatus.PENDING,
    "SUCCESS": RailStatus.SUCCEEDED,
    "DENIED": RailStatus.FAILED,
    "CANCELED": RailStatus.FAILED,
}

_ITEM_FAILED = {"FAILED", "RETURNED", "BLOCKED", "DENIED", "REFUNDED", "REVERSED"}


class PayPalPayoutRail(Rail):
    name = "paypal_payouts"
    simulated = False

    def __init__(self, client=None):
        self.client = client

    def _client(self):
        return self.client or get_client()

    def pay(self, payee: Payee, amount: Decimal, reference: str, currency: str = "USD") -> RailResult:
        amount = validate_amount(amount)
        try:
            data = self._client().create_payout(
                receiver_email=payee.identifier,
                amount=amount,
                currency=currency,
                reference=reference,
                note=payee.note or f"Hukama payment to {payee.name}",
            )
        except PayPalError as exc:
            raise RailError(str(exc)) from exc
        return self._result(data, reference)

    def status(self, external_id: str) -> RailResult:
        try:
            data = self._client().get_payout_batch(external_id)
        except PayPalError as exc:
            raise RailError(str(exc)) from exc
        return self._result(data, data.get("batch_header", {}).get("sender_batch_header", {}).get("sender_batch_id", ""))

    def _result(self, data, reference):
        header = data.get("batch_header", {})
        status = _STATUS_MAP.get(header.get("batch_status"), RailStatus.PENDING)
        # A batch can be SUCCESS while its one item failed, came back or waits unclaimed: the item decides.
        items = [i.get("transaction_status") for i in data.get("items") or []]
        if status == RailStatus.SUCCEEDED and items:
            if any(s in _ITEM_FAILED for s in items):
                status = RailStatus.FAILED
            elif any(s != "SUCCESS" for s in items):
                status = RailStatus.PENDING
        return RailResult(
            rail=self.name,
            reference=reference,
            external_id=header.get("payout_batch_id", ""),
            status=status,
            simulated=False,
            raw=data,
        )


class LocalMobileMoneyRail(PayPalPayoutRail):
    """Step 1 of the mobile money rail: a real PayPal Payout to the provider's business account. The payout
    note tells the provider which registered phone to credit and with what (BUILD_SPEC §8). Step 2, delivery to
    the phone, is simulated in payments/last_mile.py."""

    name = "local_mobile_money"
