import re

from django.conf import settings
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.api import IsFamilyMember, current_family, get_or_404

from . import last_mile
from .models import RailTransaction
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
    """Give to a pool with PayPal checkout (Orders v2). Built with the PayPal Server SDK in Phase 4."""
    _public_pool(token)
    return Response({"detail": "PayPal checkout for this pool opens soon."}, status=503)
