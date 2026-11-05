"""REAL: "Log in with PayPal" for payee upload links, so only the owner of the PayPal account that would be
paid can ask for money through the link.

The PayPal Server SDK has no Log in with PayPal flow (checked with the APIMatic Context Plugin), so this uses
PayPal's Identity REST API through our client: the authorize page, the authorization-code token exchange, and
userinfo. The verified email must be the payee's PayPal email (the account payouts go to).
"""

from urllib.parse import urlencode

from django.conf import settings
from django.core import signing

from .paypal_client import PayPalError, get_client

RETURN_PATH = "/paypal/payee-login/"
COOKIE = "hukama_payee"
COOKIE_PATH = "/api/public/payee/"
SESSION_SECONDS = 12 * 3600
STATE_SECONDS = 15 * 60
_SALT_STATE, _SALT_SESSION = "payee-login-state", "payee-login-session"


class LoginError(Exception):
    """The login did not prove the person owns the payee's PayPal account; the message is safe to show."""


def required():
    return settings.PAYEE_PAYPAL_LOGIN


def return_url(base):
    return f"{base.rstrip('/')}{RETURN_PATH}"


def authorize_url(link, base):
    """PayPal's login page for this link. The state is signed and short-lived, and names the link."""
    client = get_client()
    web = "https://www.sandbox.paypal.com" if client.is_sandbox else "https://www.paypal.com"
    state = signing.dumps({"link": str(link.id)}, salt=_SALT_STATE)
    return f"{web}/signin/authorize?" + urlencode({
        "flowEntry": "static", "client_id": client.client_id, "response_type": "code",
        "scope": "openid email", "redirect_uri": return_url(base), "state": state})


def link_id_from_state(state):
    try:
        return signing.loads(state or "", salt=_SALT_STATE, max_age=STATE_SECONDS)["link"]
    except (signing.BadSignature, KeyError, TypeError):
        raise LoginError("The PayPal login expired. Open the link and try again")


def emails(profile):
    """Confirmed email addresses in a userinfo response (paypalv1.1 or openid shape)."""
    found = [e.get("value", "") for e in profile.get("emails") or [] if e.get("confirmed", True)]
    if profile.get("email") and profile.get("email_verified", True):
        found.append(profile["email"])
    return {e.strip().lower() for e in found if e}


def verify(code, payee, client=None):
    """Exchange the code and check the PayPal account is the payee's. Returns the verified email."""
    client = client or get_client()
    try:
        profile = client.user_info(client.user_token(code))
    except PayPalError as exc:
        raise LoginError("PayPal could not confirm the login. Try again") from exc
    expected = (payee.paypal_email or "").strip().lower()
    found = emails(profile)
    if not expected or expected not in found:
        raise LoginError(f"You logged in as {mask(next(iter(found), 'another account'))}, but this link is for "
                         f"{payee.name}'s PayPal account ({mask(expected)})")
    return expected


def session_value(link, email):
    return signing.dumps({"link": str(link.id), "email": email}, salt=_SALT_SESSION)


def verified_email(request, link):
    """The PayPal email this browser proved for `link`, or None."""
    try:
        data = signing.loads(request.COOKIES.get(COOKIE, ""), salt=_SALT_SESSION, max_age=SESSION_SECONDS)
    except signing.BadSignature:
        return None
    return data.get("email") if data.get("link") == str(link.id) else None


def mask(email):
    name, _, domain = (email or "").partition("@")
    return f"{name[:2]}***@{domain}" if domain else email
