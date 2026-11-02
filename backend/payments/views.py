from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api import IsFamilyMember, current_family, get_or_404
from mandates import services
from mandates.models import Funding

from . import last_mile
from .models import RailTransaction
from .paypal_client import PayPalError, get_client
from .rails import paynow_inbound


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
    return Response({**base, "status": "connected"})


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_create_order(request, pk):
    """PayPal Orders checkout. Phase 4 builds it with the APIMatic PayPal Server SDK (CLAUDE.md rule 5)."""
    get_or_404(current_family(request).mandates, pk=pk)
    return Response({"detail": "Funding with PayPal is not switched on yet."}, status=503)


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def fund_capture(request, pk):
    get_or_404(current_family(request).mandates, pk=pk)
    return Response({"detail": "Funding with PayPal is not switched on yet."}, status=503)


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


# --- Local contributions (Paynow test mode, inbound) -----------------------------------------------------

def _funding_data(f):
    return {"id": str(f.id), "mandate": str(f.mandate_id), "amount": f"{f.amount:.2f}", "status": f.status,
            "rail": f.rail, "rail_label": f.get_rail_display(), "contributor_name": f.contributor_name,
            "contributor_phone": f.contributor_phone, "failure_reason": f.failure_reason,
            "funder": f.funder.get_full_name() if f.funder_id else None, "created_at": f.created_at}


@api_view(["GET"])
@permission_classes([IsFamilyMember])
def mandate_fundings(request, pk):
    mandate = get_or_404(current_family(request).mandates, pk=pk)
    qs = mandate.fundings.select_related("funder").order_by("-created_at")
    return Response([_funding_data(f) for f in qs])


@api_view(["POST"])
@permission_classes([IsFamilyMember])
def contribute_local(request, pk):
    """A family member asks a relative at home to contribute; the relative approves on their phone."""
    family = current_family(request)
    mandate = get_or_404(family.mandates, pk=pk)
    services.require_funder(request.user, family)
    data = request.data
    funding, instructions = paynow_inbound.start_contribution(
        mandate=mandate, amount=data.get("amount") or "0", name=data.get("name", ""), phone=data.get("phone", ""),
        started_by=request.user)
    return Response({**_funding_data(funding), "instructions": instructions}, status=201)


@api_view(["GET"])
@permission_classes([IsFamilyMember])
def funding_detail(request, pk):
    """Polls the rail while a local contribution is waiting for the relative to approve it."""
    funding = get_or_404(Funding.objects.filter(mandate__family=current_family(request)), pk=pk)
    if funding.rail == Funding.PAYNOW_INBOUND and funding.status == Funding.CREATED:
        try:
            funding = paynow_inbound.check_contribution(funding)
        except paynow_inbound.PaynowError:
            pass  # keep waiting; the result callback may still arrive
    return Response(_funding_data(funding))


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def paynow_result(request):
    """Paynow's result callback. Trusted only after the hash check."""
    try:
        paynow_inbound.handle_result(request.body.decode("utf-8"))
    except paynow_inbound.PaynowError as exc:
        return Response({"detail": str(exc)}, status=400)
    return Response({"ok": True})
