from django.contrib import admin

from .models import PayPalPlan, PremiumSubscription, RailTransaction, WebhookEvent


@admin.register(RailTransaction)
class RailTransactionAdmin(admin.ModelAdmin):
    list_display = ("reference", "rail", "amount", "status", "last_mile_status", "simulated", "created_at")
    list_filter = ("rail", "status", "simulated")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("paypal_event_id", "event_type", "processed_at", "created_at")
    list_filter = ("event_type",)


@admin.register(PayPalPlan)
class PayPalPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "plan_id", "product_id", "amount", "currency", "created_at")


@admin.register(PremiumSubscription)
class PremiumSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("mandate", "funder", "amount", "status", "paypal_subscription_id", "activated_at")
    list_filter = ("status",)
