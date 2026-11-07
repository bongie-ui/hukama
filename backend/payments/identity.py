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
# A business logged in from the landing page (no link): covers every upload link of the payees paid to that email.
PORTAL_COOKIE = "hukama_business"
PORTAL_COOKIE_PATH = "/api/public/"
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
    """PayPal's login page for this link (or, with link=None, for the business entry on the landing page).
    The state is signed and short-lived, and names what it is for."""
    client = get_client()
    web = "https://www.sandbox.paypal.com" if client.is_sandbox else "https://www.paypal.com"
    state = signing.dumps({"link": str(link.id)} if link else {"portal": True}, salt=_SALT_STATE)
    return f"{web}/signin/authorize?" + urlencode({
        "flowEntry": "static", "client_id": client.client_id, "response_type": "code",
        "scope": "openid email", "redirect_uri": return_url(base), "state": state})


def read_state(state):
    """{"link": id} or {"portal": True}, if the state is ours and fresh."""
    try:
        data = signing.loads(state or "", salt=_SALT_STATE, max_age=STATE_SECONDS)
    except (signing.BadSignature, TypeError):
        raise LoginError("The PayPal login expired. Please try again")
    if not isinstance(data, dict) or not (data.get("link") or data.get("portal")):
        raise LoginError("The PayPal login expired. Please try again")
    return data


def link_id_from_state(state):
    data = read_state(state)
    if not data.get("link"):
        raise LoginError("The PayPal login expired. Open the link and try again")
    return data["link"]


def verified_emails(code, client=None):
    """Exchange the code; the confirmed emails of the PayPal account that logged in."""
    client = client or get_client()
    try:
        return emails(client.user_info(client.user_token(code)))
    except PayPalError as exc:
        raise LoginError("PayPal could not confirm the login. Try again") from exc


def portal_value(email):
    return signing.dumps({"portal": email}, salt=_SALT_SESSION)


def portal_email(request):
    """The PayPal email a business proved on the landing page, or None."""
    try:
        data = signing.loads(request.COOKIES.get(PORTAL_COOKIE, ""), salt=_SALT_SESSION, max_age=SESSION_SECONDS)
    except signing.BadSignature:
        return None
    return data.get("portal")


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
    """The PayPal email this browser proved for `link` (on the link itself, or as the same business on the landing
    page), or None."""
    try:
        data = signing.loads(request.COOKIES.get(COOKIE, ""), salt=_SALT_SESSION, max_age=SESSION_SECONDS)
    except signing.BadSignature:
        data = {}
    if data.get("link") == str(link.id):
        return data.get("email")
    portal = portal_email(request)
    expected = (link.payee.paypal_email or "").strip().lower()
    return portal if portal and expected and portal == expected else None


def mask(email):
    name, _, domain = (email or "").partition("@")
    return f"{name[:2]}***@{domain}" if domain else email
