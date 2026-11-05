import re

from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api import IsFamilyMember, current_family, get_or_404
from mandates.models import Funding

from . import checkout, last_mile, premiums, webhooks
from .models import PremiumSubscription, RailTransaction, WebhookEvent
from .paypal_client import PayPalError, get_client


@api_view(["GET"])
@permission_classes([AllowAny])
def paypal_health(request):
    """Reports whether we can authenticate against PayPal. Never returns the token itself."""
    client = get_client()
    base = {"environment": "sandbox" if client.is_sandbox else "live", "base_url": client.base_url}
    if not client.is_configured:
        return Response({**base, "status": "not_configured",
                         "detail": "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env"}, status=503)
    try:
        client.get_access_token()
    except PayPalError as exc:
        return Response({**base, "status": "error", "detail": str(exc),
                         "paypal_status": exc.status_code}, status=502)
    last = WebhookEvent.objects.order_by("-created_at").values("event_type", "created_at").first()
    return Response({**base, "status": "connected", "webhooks_received": WebhookEvent.objects.count(),
                     "last_webhook": last})


def _checkout_error(exc):
    return Response({"detail": str(exc)}, status=502)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def paypal_config(request):
    """What the browser needs to show PayPal buttons (the client id is public by design)."""
    sandbox = checkout.is_sandbox()
    return Response({"enabled": checkout.is_configured(), "client_id": settings.PAYPAL_CLIENT_ID,
                     "sdk_url": "https://www.sandbox.paypal.com/web-sdk/v6/core" if sandbox
                     else "https://www.paypal.com/web-sdk/v6/core", "environment": "sandbox" if sandbox else "live"})


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_create_order(request, pk):
    """A funder starts PayPal checkout for a mandate they fund. Returns the PayPal order id for the button."""
    mandate = get_or_404(current_family(request).mandates, pk=pk)
    try:
        funding = checkout.start(mandate, request.data.get("amount"), funder=request.user)
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response({"order_id": funding.paypal_order_id, "funding_id": str(funding.id)}, status=201)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_capture(request, pk):
    """After the funder approves in PayPal: capture, then the money counts towards the mandate."""
    funding = get_or_404(Funding.objects.filter(mandate__family=current_family(request), mandate_id=pk,
                                                funder=request.user), paypal_order_id=request.data.get("order_id") or "-")
    try:
        funding = checkout.finish(funding)
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response(_funding_data(funding))


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def invoice_create_order(request, pk):
    """A funder starts paying a shopping list the fund could not cover (PayPal checkout for its amount)."""
    from mandates.models import Request
    from mandates.services import check_invoice_payable

    req = get_or_404(Request.objects.filter(mandate__family=current_family(request)).select_related("mandate"), pk=pk)
    check_invoice_payable(req, request.user)
    try:
        funding = checkout.start(req.mandate, req.amount, funder=request.user, for_request=req)
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response({"order_id": funding.paypal_order_id, "funding_id": str(funding.id)}, status=201)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def invoice_capture(request, pk):
    """After the funder approves in PayPal: capture; the first payment pays the list, others stay in the fund."""
    from mandates.models import Request
    from mandates.serializers import RequestDetailSerializer

    funding = get_or_404(Funding.objects.filter(mandate__family=current_family(request), for_request_id=pk,
                                                funder=request.user), paypal_order_id=request.data.get("order_id") or "-")
    try:
        checkout.finish(funding)
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response(RequestDetailSerializer(Request.objects.get(pk=pk)).data)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def demo_collect(request, pk):
    """Demo button: the beneficiary collects cash at an agent (simulated last mile)."""
    if not settings.DEMO_MODE:
        raise NotFound()
    tx = get_or_404(RailTransaction.objects.filter(request__mandate__family=current_family(request)), pk=pk)
    try:
        tx = last_mile.collect(tx, code=request.data.get("code") or None)
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    return Response({"id": str(tx.id), "last_mile_status": tx.last_mile_status})


# --- Fundings ---------------------------------------------------------------------------------------------

def _funding_data(f):
    return {"id": str(f.id), "mandate": str(f.mandate_id), "amount": f"{f.amount:.2f}", "status": f.status,
            "rail": f.rail, "rail_label": f.get_rail_display(), "contributor_name": f.contributor_name,
            "failure_reason": f.failure_reason,
            "funder": f.funder.get_full_name() if f.funder_id else None, "created_at": f.created_at}


@api_view(["GET"])
@permission_classes([IsFamilyMember])
def mandate_fundings(request, pk):
    """Everyone who put money into a mandate: family funders and, for pools, anyone with the link."""
    mandate = get_or_404(current_family(request).mandates, pk=pk)
    qs = mandate.fundings.select_related("funder").order_by("-created_at")
    return Response([_funding_data(f) for f in qs])


# --- Public pool link (no sign-in) -----------------------------------------------------------------------

def _public_pool(token):
    from mandates.models import Mandate

    mandate = Mandate.objects.filter(contribute_token=token, status=Mandate.ACTIVE).select_related("family").first()
    if mandate is None or not token:
        raise NotFound("This contribution link is not active")
    return mandate


def _public_name(f):
    """Givers are shown by first name and initial only."""
    name = (f.funder.get_full_name() if f.funder_id else f.contributor_name) or "Someone"
    parts = [w for w in re.sub(r"\(.*?\)", " ", name).split() if w[0].isalpha()] or ["Someone"]
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_pool(request, token):
    """What anyone with the link sees: the pool's purpose, what has been raised, and who gave."""
    from mandates.services import captured_total

    mandate = _public_pool(token)
    given = mandate.fundings.filter(status="CAPTURED").select_related("funder").order_by("-created_at")
    return Response({
        "title": mandate.title, "purpose": mandate.purpose_text, "family": mandate.family.name,
        "currency": mandate.currency, "raised": f"{captured_total(mandate):.2f}", "givers": given.count(),
        "recent": [{"name": _public_name(f), "amount": f"{f.amount:.2f}", "at": f.created_at} for f in given[:12]],
    })


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_contribute(request, token):
    """Anyone with the link starts PayPal checkout for the pool. Nothing counts until PayPal captures it."""
    mandate = _public_pool(token)
    name = (request.data.get("name") or "").strip()
    if not name:
        raise ValidationError({"name": "Tell the family who is giving"})
    try:
        funding = checkout.start(mandate, request.data.get("amount"), contributor_name=name,
                                 message=request.data.get("message") or "")
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response({"order_id": funding.paypal_order_id}, status=201)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_capture(request, token):
    """After the giver approves in PayPal: capture and thank them."""
    mandate = _public_pool(token)
    funding = get_or_404(mandate.fundings.filter(funder__isnull=True),
                         paypal_order_id=request.data.get("order_id") or "-")
    try:
        funding = checkout.finish(funding)
    except checkout.CheckoutError as exc:
        return _checkout_error(exc)
    return Response({"status": funding.status, "amount": f"{funding.amount:.2f}", "name": _public_name(funding)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def paypal_webhook(request):
    """PayPal event notifications. Nothing changes unless PayPal verifies the signature."""
    try:
        outcome = webhooks.receive(request.headers, request.data)
    except webhooks.WebhookError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response({"result": outcome})


# --- Monthly premiums (PayPal Subscriptions) -------------------------------------------------------------

def _premium_data(p):
    return {"id": str(p.id), "amount": f"{p.amount:.2f}", "status": p.status, "status_label": p.get_status_display(),
            "funder": p.funder.get_full_name() or p.funder.username, "funder_id": p.funder_id,
            "paypal_subscription_id": p.paypal_subscription_id, "activated_at": p.activated_at,
            "cancelled_at": p.cancelled_at, "created_at": p.created_at}


@api_view(["GET"])
@permission_classes([IsFamilyMember])
def mandate_premium(request, pk):
    mandate = get_or_404(current_family(request).mandates.prefetch_related("rules"), pk=pk)
    amount = premiums.premium_for(mandate)
    subs = mandate.premium_subscriptions.select_related("funder").exclude(
        status=PremiumSubscription.APPROVAL_PENDING, created_at__lt=timezone.now() - timedelta(days=1)).order_by("-created_at")
    return Response({"amount": f"{amount:.2f}" if amount is not None else None,
                     "subscriptions": [_premium_data(p) for p in subs]})


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def premium_start(request, pk):
    """Start a monthly premium; the funder approves it on PayPal and comes back to the mandate."""
    mandate = get_or_404(current_family(request).mandates.prefetch_related("rules"), pk=pk)
    try:
        premium, approve_url = premiums.start(mandate, request.user, premiums.public_base(request))
    except premiums.CheckoutError as exc:
        return _checkout_error(exc)
    return Response({**_premium_data(premium), "approve_url": approve_url}, status=201)


def _family_premium(request, pk):
    return get_or_404(PremiumSubscription.objects.filter(mandate__family=current_family(request))
                      .select_related("mandate", "funder"), pk=pk)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def premium_sync(request, pk):
    """Check status and payments with PayPal (after approval, or when webhooks are not reachable)."""
    try:
        premium = premiums.sync(_family_premium(request, pk))
    except premiums.CheckoutError as exc:
        return _checkout_error(exc)
    return Response(_premium_data(premium))


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def premium_cancel(request, pk):
    try:
        premium = premiums.cancel(_family_premium(request, pk), request.user)
    except premiums.CheckoutError as exc:
        return _checkout_error(exc)
    return Response(_premium_data(premium))


def premium_return(request):
    """PayPal sends the funder here after approving (or cancelling); continue in the app."""
    premium = PremiumSubscription.objects.filter(pk=request.GET.get("premium") or None).first() \
        if _is_uuid(request.GET.get("premium")) else None
    if premium is None:
        return redirect("/")
    flag = "&cancelled=1" if request.GET.get("cancelled") else ""
    return redirect(f"/#/mandates/{premium.mandate_id}?premium={premium.id}{flag}")


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False
