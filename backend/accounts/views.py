"""Session auth for the SPA, plus the demo persona switcher (DEMO_MODE only)."""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from mandates.serializers import display_name

from .models import Membership


def _with_token(request, data):
    """API clients without a browser cookie jar (Postman, scripts) send this back as X-CSRFToken.
    Login rotates the token, so every sign-in response carries the new one."""
    return {**data, "csrf_token": get_token(request)}


def _me(user):
    m = Membership.objects.filter(user=user).select_related("family").order_by("created_at").first()
    return {
        "id": user.id, "username": user.username, "name": display_name(user),
        "family": {"id": str(m.family.id), "name": m.family.name} if m else None,
        "role": m.role if m else None, "country": m.country if m else "",
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@ensure_csrf_cookie
def me(request):
    """Also sets the CSRF cookie the SPA sends back on every write."""
    user = request.user if request.user.is_authenticated else None
    return Response(_with_token(request, {"authenticated": user is not None, "user": _me(user) if user else None,
                                          "demo_mode": settings.DEMO_MODE}))


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(request, username=request.data.get("username", ""), password=request.data.get("password", ""))
    if user is None:
        raise ValidationError({"detail": "Wrong username or password"})
    login(request, user)
    return Response(_with_token(request, _me(user)))


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_view(request):
    """Start a new family: the person gets an account and becomes the family's admin, then is signed in."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import validate_email
    from django.db import transaction

    from core.phones import normalize_phone

    from .models import Family

    d = request.data
    email = (d.get("email") or "").strip().lower()
    first, last = (d.get("first_name") or "").strip(), (d.get("last_name") or "").strip()
    family_name = (d.get("family_name") or "").strip() or (f"{last} family" if last else "")
    errors = {}
    try:
        validate_email(email)
    except DjangoValidationError:
        errors["email"] = "Enter a valid email address"
    User = get_user_model()
    if email and (User.objects.filter(email__iexact=email).exists() or User.objects.filter(username=email).exists()):
        errors["email"] = "There is already an account with this email. Sign in instead"
    if not first:
        errors["first_name"] = "Enter your first name"
    if not family_name:
        errors["family_name"] = "Name your family, e.g. the Moyo family"
    phone = ""
    if d.get("phone"):
        phone = normalize_phone(d["phone"]) or ""
        if not phone:
            errors["phone"] = "Enter the phone number with its country code"
    password = d.get("password") or ""
    try:
        validate_password(password, User(username=email, email=email, first_name=first, last_name=last))
    except DjangoValidationError as exc:
        errors["password"] = " ".join(exc.messages)
    if errors:
        raise ValidationError(errors)
    with transaction.atomic():
        user = User.objects.create_user(username=email, email=email, password=password, first_name=first,
                                        last_name=last)
        family = Family.objects.create(name=family_name[:120], created_by=user)
        Membership.objects.create(user=user, family=family, role=Membership.ADMIN, phone=phone,
                                  country=(d.get("country") or "").upper()[:2], paypal_email=email)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(_with_token(request, {**_me(user), "new_family": True}), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


def _demo_users():
    if not settings.DEMO_MODE:
        raise NotFound()
    # Only the seeded demo family (seed_version > 0): families people start themselves are never offered, so nobody
    # can sign in as them without their password. Staff and admin accounts are never offered either.
    return get_user_model().objects.filter(memberships__family__seed_version__gt=0, is_staff=False,
                                           is_superuser=False).distinct().order_by("date_joined")


@api_view(["GET"])
@permission_classes([AllowAny])
def demo_users(request):
    return Response([_me(u) for u in _demo_users()[:20]])


@api_view(["POST"])
@permission_classes([AllowAny])
def demo_login(request):
    user = _demo_users().filter(username=request.data.get("username", "")).first()
    if user is None:
        raise ValidationError({"detail": "No such demo user"})
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return Response(_with_token(request, _me(user)))
