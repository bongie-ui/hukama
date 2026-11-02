"""SIMULATED last mile: what happens at home after the payee has been paid (BUILD_SPEC §8 step 2).

Starts once the payout succeeds. Airtime/bundles: DELIVERING -> DELIVERED after a few seconds. Cash, and
groceries to collect: AWAITING_COLLECTION with a 6-digit code sent to the beneficiary's chat -> COLLECTED.
Groceries delivered: PREPARING -> OUT_FOR_DELIVERY -> DELIVERED to the registered address.
"""

import secrets
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from mandates.models import LedgerEntry, Payee, Request
from mandates.services import record

from .models import RailTransaction

DELIVERY_SECONDS = 3
# Home delivery is slower: packed, then on the road (seconds, so the demo shows every step).
PREPARING_SECONDS = 6
ON_THE_ROAD_SECONDS = 12
CASH_PRODUCTS = ("cash",)
LAST_MILE_ACTOR = "SIMULATED_RAIL"


def _code():
    return f"{secrets.randbelow(10**6):06d}"


def _money(amount, currency):
    return f"${amount:.2f}" if currency == "USD" else f"{currency} {amount:.2f}"


def notify_beneficiary(request, text):
    """SMS-style notice in the beneficiary's chat (identified by their registered phone)."""
    from agent.models import ChatMessage, Conversation

    beneficiary = request.beneficiary
    if beneficiary is None:
        return None
    conversation, _ = Conversation.objects.get_or_create(
        family=beneficiary.family, participant_phone=beneficiary.phone, participant_user=None,
        defaults={"title": beneficiary.name})
    return ChatMessage.objects.create(conversation=conversation, role="assistant", text=text,
                                      linked_request=request)


def _has_last_mile(tx):
    return tx.request.payee.rail == Payee.LOCAL_MOBILE_MONEY or bool(tx.request.fulfilment)


@transaction.atomic
def start(tx, now=None):
    """Begin the last mile for a succeeded payout. No-op when nothing happens at home or it already started."""
    # Lock only the transaction row: PostgreSQL refuses FOR UPDATE on the optional (outer-joined) relations.
    tx = RailTransaction.objects.select_for_update(of=("self",)) \
        .select_related("request__mandate", "request__beneficiary", "request__payee").get(pk=tx.pk)
    if not _has_last_mile(tx) or tx.last_mile_status != RailTransaction.LAST_MILE_NA:
        return tx
    request = tx.request
    tx.raw = {**tx.raw, "last_mile_started_at": (now or timezone.now()).isoformat(), "simulated_last_mile": True}
    goods = request.details.get("basket")
    if request.fulfilment == Request.COLLECT or (not request.fulfilment and request.product in CASH_PRODUCTS):
        tx.last_mile_status = RailTransaction.AWAITING_COLLECTION
        tx.collection_code = _code()
        if goods:
            notify_beneficiary(request, f"Your family sent you groceries ({goods}). They are ready at "
                                        f"{request.payee.name}. Collect with code {tx.collection_code}.")
        else:
            notify_beneficiary(request, f"You have {_money(tx.amount, request.mandate.currency)} from your family. "
                                        f"Collect at any mobile money agent with code {tx.collection_code}.")
    elif request.fulfilment == Request.DELIVERY:
        tx.last_mile_status = RailTransaction.PREPARING
        notify_beneficiary(request, f"Your family sent you groceries ({goods}). {request.payee.name} is packing "
                                    f"them for delivery to {request.details.get('address', 'your home')}.")
    else:
        tx.last_mile_status = RailTransaction.DELIVERING
    tx.save(update_fields=["last_mile_status", "collection_code", "raw", "updated_at"])
    return tx


@transaction.atomic
def advance(tx, now=None):
    """Move timed deliveries on: DELIVERING -> DELIVERED, PREPARING -> OUT_FOR_DELIVERY -> DELIVERED."""
    now = now or timezone.now()
    # Lock only the transaction row: PostgreSQL refuses FOR UPDATE on the optional (outer-joined) relations.
    tx = RailTransaction.objects.select_for_update(of=("self",)) \
        .select_related("request__mandate", "request__beneficiary", "request__payee").get(pk=tx.pk)
    if tx.last_mile_status not in RailTransaction.IN_TRANSIT:
        return tx
    elapsed = now - datetime.fromisoformat(tx.raw["last_mile_started_at"])
    request = tx.request
    if tx.last_mile_status == RailTransaction.PREPARING:
        if elapsed < timedelta(seconds=PREPARING_SECONDS):
            return tx
        tx.last_mile_status = RailTransaction.OUT_FOR_DELIVERY
        tx.save(update_fields=["last_mile_status", "updated_at"])
        notify_beneficiary(request, f"Your groceries from {request.payee.name} are on the way.")
        return tx
    wait = DELIVERY_SECONDS if tx.last_mile_status == RailTransaction.DELIVERING \
        else PREPARING_SECONDS + ON_THE_ROAD_SECONDS
    if elapsed < timedelta(seconds=wait):
        return tx
    tx.last_mile_status = RailTransaction.DELIVERED
    tx.save(update_fields=["last_mile_status", "updated_at"])
    record(request.mandate, LedgerEntry.DELIVERED, LAST_MILE_ACTOR, request=request, amount=tx.amount,
           product=request.product, simulated=True, **({"fulfilment": request.fulfilment} if request.fulfilment else {}))
    if request.details.get("basket"):
        notify_beneficiary(request, f"Your groceries ({request.details['basket']}) have been delivered.")
    else:
        notify_beneficiary(request, f"Your {request.product} ({_money(tx.amount, request.mandate.currency)}) "
                                    "from your family has arrived.")
    return tx


def advance_all(now=None):
    return [advance(tx, now) for tx in RailTransaction.objects.filter(last_mile_status__in=RailTransaction.IN_TRANSIT)]


@transaction.atomic
def collect(tx, code=None):
    """Mark cash collected (demo button). If `code` is given it must match."""
    tx = RailTransaction.objects.select_for_update(of=("self",)).select_related("request__mandate").get(pk=tx.pk)
    if tx.last_mile_status == RailTransaction.COLLECTED:
        return tx
    if tx.last_mile_status != RailTransaction.AWAITING_COLLECTION:
        raise ValueError("Nothing is waiting for collection")
    if code is not None and code != tx.collection_code:
        raise ValueError("Wrong collection code")
    tx.last_mile_status = RailTransaction.COLLECTED
    tx.save(update_fields=["last_mile_status", "updated_at"])
    record(tx.request.mandate, LedgerEntry.DELIVERED, LAST_MILE_ACTOR, request=tx.request, amount=tx.amount,
           product=tx.request.product, collected=True, simulated=True)
    return tx
