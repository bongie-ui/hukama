from django.conf import settings
from django.db import models

from core.models import BaseModel, money_field


class RailTransaction(BaseModel):
    """One attempt to move money for a Request on a rail (real or simulated)."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETURNED = "RETURNED"
    STATUSES = [(s, s.title()) for s in (PENDING, SUCCESS, FAILED, RETURNED)]

    LAST_MILE_NA = "N/A"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    AWAITING_COLLECTION = "AWAITING_COLLECTION"
    COLLECTED = "COLLECTED"
    PREPARING = "PREPARING"  # goods being packed
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    LAST_MILE_STATUSES = [(s, s.replace("_", " ").title()) for s in
                          (LAST_MILE_NA, DELIVERING, DELIVERED, AWAITING_COLLECTION, COLLECTED, PREPARING,
                           OUT_FOR_DELIVERY)]
    IN_TRANSIT = (DELIVERING, PREPARING, OUT_FOR_DELIVERY)  # advanced on a timer

    request = models.ForeignKey("mandates.Request", on_delete=models.PROTECT, related_name="rail_transactions")
    rail = models.CharField(max_length=20)  # Payee.rail value
    amount = money_field()
    reference = models.CharField(max_length=64)  # hukama-<request id>; PayPal sender_batch_id
    external_id = models.CharField(max_length=64, blank=True)  # payout batch / item id
    simulated = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    last_mile_status = models.CharField(max_length=20, choices=LAST_MILE_STATUSES, default=LAST_MILE_NA)
    collection_code = models.CharField(max_length=6, blank=True)
    raw = models.JSONField(default=dict, blank=True)


class WebhookEvent(BaseModel):
    paypal_event_id = models.CharField(max_length=64, unique=True)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)


class PayPalPlan(BaseModel):
    """A PayPal billing plan we created (via the Server SDK), reused for every subscription at this price."""

    name = models.CharField(max_length=120)
    product_id = models.CharField(max_length=64)  # PayPal catalog product
    plan_id = models.CharField(max_length=64, unique=True)
    amount = money_field()
    currency = models.CharField(max_length=3, default="USD")


class PremiumSubscription(BaseModel):
    """A funder's monthly PayPal subscription paying a mandate's premium (e.g. funeral cover)."""

    APPROVAL_PENDING = "APPROVAL_PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    STATUSES = [(s, s.replace("_", " ").title()) for s in (APPROVAL_PENDING, ACTIVE, SUSPENDED, CANCELLED, EXPIRED)]

    mandate = models.ForeignKey("mandates.Mandate", on_delete=models.PROTECT, related_name="premium_subscriptions")
    funder = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="premium_subscriptions")
    plan = models.ForeignKey(PayPalPlan, on_delete=models.PROTECT, related_name="subscriptions")
    amount = money_field()
    paypal_subscription_id = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=APPROVAL_PENDING)
    activated_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
