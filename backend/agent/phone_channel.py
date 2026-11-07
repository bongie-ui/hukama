"""Phone chat channel: people reach the assistant from their own phone through a messaging provider's test number
(Twilio's sandbox). Kept provider-neutral in the app: users see "chat by phone".

Inbound: the provider POSTs each message here, signed with our auth token (verified before anything happens). The
sender's number decides who they are: a funder, a person the family supports, or a payee, exactly as the in-app chat.
Unregistered numbers get a short reply and nothing else. The reply is sent back through the provider's REST API from a
background thread, so slow model calls never time out the provider's webhook.
"""

import base64
import hashlib
import hmac
import logging
import threading

import requests
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q

from accounts.models import Membership
from core.phones import normalize_phone
from mandates import services
from mandates.models import Beneficiary, Payee

from . import chat
from .models import Conversation

log = logging.getLogger(__name__)
API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
MAX_MEDIA = 3
NOT_REGISTERED = ("Hello. This number isn't registered with a family on Hukama, so I can't help with payments. "
                  "Please ask the family to add you.")


def is_configured():
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)


def valid_signature(url, params, signature, token=None):
    """The provider's request signature: HMAC-SHA1 of the URL plus every POST field (sorted), base64."""
    token = token or settings.TWILIO_AUTH_TOKEN
    if not token or not signature:
        return False
    payload = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)


def sender_phone(from_field):
    return normalize_phone((from_field or "").removeprefix("whatsapp:")) or ""


def conversation_for(phone):
    """The conversation for a registered number (funder, person at home or payee), or None."""
    if not phone:
        return None
    m = Membership.objects.filter(phone=phone).select_related("user", "family").order_by("created_at").first()
    if m:
        c, _ = Conversation.objects.get_or_create(family=m.family, participant_user=m.user,
                                                  defaults={"participant_phone": ""})
        return c
    b = Beneficiary.objects.filter(phone=phone).select_related("family").order_by("created_at").first()
    family = b.family if b else None
    if family is None:
        payee = Payee.objects.filter(phone=phone).order_by("created_at").first()
        if payee is not None:
            family = payee.family or next((f for f in _families_paying(payee)), None)
    if family is None:
        return None
    c, _ = Conversation.objects.get_or_create(family=family, participant_phone=phone, participant_user=None)
    return c


def _families_paying(payee):
    from accounts.models import Family
    for family in Family.objects.order_by("created_at"):
        if services.payee_mandates(family, payee):
            yield family


def _media(conversation, phone, params, http=None):
    """Download attached photos (the provider needs our credentials) and store them as uploads."""
    http = http or requests
    uploads = []
    for i in range(min(int(params.get("NumMedia") or 0), MAX_MEDIA)):
        url, ctype = params.get(f"MediaUrl{i}"), params.get(f"MediaContentType{i}", "")
        if not url:
            continue
        try:
            r = http.get(url, auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN), timeout=30)
            r.raise_for_status()
            uploads.append(services.create_upload(family=conversation.family, data=r.content,
                                                  content_type=ctype.split(";")[0], name=f"phone-{i}",
                                                  user=conversation.participant_user, phone=phone))
        except (requests.RequestException, services.ServiceError) as exc:
            log.warning("phone channel: could not read attachment %s: %s", i, exc)
    return uploads


def send(to, text, http=None):
    """Send a reply through the provider. `to` is the provider's address (e.g. whatsapp:+263…)."""
    http = http or requests
    r = http.post(API.format(sid=settings.TWILIO_ACCOUNT_SID), auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                  data={"From": settings.TWILIO_WHATSAPP_FROM, "To": to, "Body": text[:1500]}, timeout=30)
    r.raise_for_status()
    return r.json().get("sid")


def handle(params, http=None, llm_chat=None):
    """Process one inbound message and send the reply. Returns the reply text."""
    to = params.get("From", "")
    phone = sender_phone(to)
    conversation = conversation_for(phone)
    if conversation is None:
        reply = NOT_REGISTERED
    else:
        uploads = _media(conversation, phone, params, http)
        reply = chat.run_turn(conversation, params.get("Body", "").strip(), uploads=uploads, llm_chat=llm_chat).text
    send(to, reply or "Sorry, I could not answer that. Please try again.", http)
    return reply


def handle_in_background(params):
    def run():
        close_old_connections()
        try:
            handle(params)
        except Exception:  # never let a provider retry storm build up; log and move on
            log.exception("phone channel: failed to handle a message")
        finally:
            close_old_connections()
    threading.Thread(target=run, daemon=True).start()
