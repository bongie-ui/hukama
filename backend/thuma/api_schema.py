"""OpenAPI annotations for the function views, kept in one place so the views stay plain.

Applied from thuma/api_urls.py. Shapes that are already serializers are referenced; the rest are described
inline. Served at /api/schema/ and /api/docs/ (and the Postman collection is built from the same routes).
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers as s

from accounts import views as accounts
from agent import views as agent
from core.views import health
from mandates import views as mandates
from mandates.models import Request
from mandates.serializers import (BeneficiarySerializer, LedgerEntrySerializer, MandateSerializer, PayeeSerializer,
                                  RequestDetailSerializer, RequestSerializer)
from payments import views as payments

OBJ = OpenApiTypes.OBJECT


def body(component, /, **fields):
    return inline_serializer(name=component, fields=fields)


def text(**kw):
    return s.CharField(**kw)


def money(**kw):
    return s.DecimalField(max_digits=12, decimal_places=2, **kw)


def uuid(**kw):
    return s.UUIDField(**kw)


# One class per nested shape, instantiated per use (a shared instance cannot be bound to two fields).
_Rule = type(body("RuleInput", kind=text(), params=s.DictField()))
_UploadRef = type(body("UploadReference", upload_id=uuid(), kind=s.ChoiceField(
    ["QUOTE", "INVOICE", "MILESTONE_PHOTO", "RECEIPT", "OTHER"])))


def rules():
    return s.ListField(child=_Rule())


def upload_refs():
    return s.ListField(required=False, child=_UploadRef())


ANNOTATIONS = [
    # (view, methods or None, extend_schema kwargs)
    (health, None, dict(tags=["Health"], summary="Liveness (database only)", responses=OBJ)),
    (payments.paypal_health, None, dict(tags=["Health"], summary="Can we authenticate with PayPal (sandbox)?",
                                        responses=OBJ)),

    (accounts.me, None, dict(tags=["Session"], summary="Who is signed in; returns the CSRF token", responses=OBJ)),
    (accounts.login_view, None, dict(tags=["Session"], summary="Sign in with username and password",
                                     request=body("LoginInput", username=text(), password=text()), responses=OBJ)),
    (accounts.signup_view, None, dict(
        tags=["Session"], summary="Start a new family (you become its admin) and sign in",
        request=body("SignupInput", first_name=text(), last_name=text(required=False), email=text(), password=text(),
                     family_name=text(), country=text(required=False), phone=text(required=False)),
        responses=OBJ)),
    (accounts.logout_view, None, dict(tags=["Session"], summary="Sign out", request=None, responses=OBJ)),
    (accounts.demo_users, None, dict(tags=["Session"], summary="Demo personas (DEMO_MODE only)", responses=OBJ)),
    (accounts.demo_login, None, dict(tags=["Session"], summary="Sign in as a demo persona (DEMO_MODE only)",
                                     request=body("DemoLoginInput", username=text()), responses=OBJ)),

    (mandates.family, None, dict(tags=["Family"], summary="The caller's family and its members", responses=OBJ)),
    (mandates.family_invite, None, dict(tags=["Family"], summary="Invite a family member (admin only)",
                                        request=OBJ, responses=OBJ)),
    (mandates.beneficiaries, ["GET"], dict(tags=["Family"], summary="People the family supports",
                                           responses=BeneficiarySerializer(many=True))),
    (mandates.beneficiaries, ["POST"], dict(tags=["Family"], summary="Register someone at home",
                                            request=body("BeneficiaryInput", name=text(), phone=text(),
                                                         address=text(required=False),
                                                         relationship=text(required=False),
                                                         allowed_products=s.ListField(child=text(), required=False)),
                                            responses=BeneficiarySerializer)),
    (mandates.beneficiary_detail, None, dict(
        tags=["Family"], summary="Edit a beneficiary (a new phone number triggers 72h of extra fraud checks)",
        request=body("BeneficiaryPatch", name=text(required=False), phone=text(required=False),
                     address=text(required=False),
                     relationship=text(required=False), allowed_products=s.ListField(child=text(), required=False)),
        responses=BeneficiarySerializer)),
    (mandates.payees, ["GET"], dict(tags=["Family"], summary="Who can be paid", responses=PayeeSerializer(many=True))),
    (mandates.payees, ["POST"], dict(tags=["Family"], summary="Add a payee (starts unverified)",
                                     request=PayeeSerializer, responses=PayeeSerializer)),

    (mandates.mandate_types, None, dict(tags=["Mandates"], summary="Mandate types and their required rules",
                                        responses=OBJ)),
    (mandates.mandates, ["GET"], dict(tags=["Mandates"], summary="The family's mandates with balances and rules",
                                      responses=MandateSerializer(many=True))),
    (mandates.mandates, ["POST"], dict(
        tags=["Mandates"], summary="Confirm and sign a mandate",
        request=body("MandateInput", type=text(), title=text(), purpose_text=text(required=False),
                     rules=rules(), co_funder_ids=s.ListField(child=s.IntegerField(), required=False)),
        responses=MandateSerializer)),
    (mandates.mandate_draft, None, dict(tags=["Mandates"], summary="Draft rules from plain words (AI; nothing saved)",
                                        request=body("DraftInput", text=text()), responses=OBJ)),
    (mandates.rules_preview, None, dict(tags=["Mandates"], summary="Validate and describe a rule set",
                                        request=body("PreviewInput", type=text(), rules=rules()),
                                        responses=OBJ)),
    (mandates.mandate_detail, None, dict(tags=["Mandates"], summary="One mandate", responses=MandateSerializer)),
    (mandates.mandate_funders, None, dict(tags=["Mandates"], summary="Add a co-funder (owner only)",
                                          request=body("FunderInput", user_id=s.IntegerField()),
                                          responses=MandateSerializer)),
    (mandates.mandate_coverage, None, dict(
        tags=["Mandates"], summary="What each product used this period, and who covered it",
        parameters=[OpenApiParameter("beneficiary", OpenApiTypes.UUID, required=True)], responses=OBJ)),
    (payments.mandate_fundings, None, dict(tags=["Funding"], summary="Who funded a mandate (all through PayPal)",
                                           responses=OBJ)),
    (mandates.mandate_contribution_link, None, dict(
        tags=["Funding"], summary="Owner turns a pool's public PayPal link on (POST) or off (DELETE)",
        request=None, responses=MandateSerializer)),
    (payments.public_pool, None, dict(tags=["Public pool"], summary="A pool as seen through its link (no sign-in)",
                                      responses=OBJ)),
    (payments.public_contribute, None, dict(
        tags=["Public pool"], summary="Start PayPal checkout to give to a pool",
        request=body("PublicContributionInput", name=text(), amount=money(), message=text(required=False)),
        responses=OBJ)),
    (payments.fund_create_order, None, dict(tags=["Funding"], summary="Start PayPal checkout (Orders v2) for a mandate",
                                            request=body("FundInput", amount=money()), responses=OBJ)),
    (payments.fund_capture, None, dict(tags=["Funding"], summary="Capture an approved PayPal order",
                                       request=body("CaptureInput", order_id=text()), responses=OBJ)),
    (payments.public_capture, None, dict(tags=["Public pool"], summary="Capture a gift approved in PayPal",
                                         request=body("PublicCaptureInput", order_id=text()), responses=OBJ)),
    (payments.mandate_premium, None, dict(tags=["Funding"], summary="A cover mandate's monthly premium and subscriptions",
                                          responses=OBJ)),
    (payments.premium_start, None, dict(tags=["Funding"], summary="Start a monthly premium (PayPal Subscriptions)",
                                        request=None, responses=OBJ)),
    (payments.premium_sync, None, dict(tags=["Funding"], summary="Check a premium's status and payments with PayPal",
                                       request=None, responses=OBJ)),
    (payments.premium_cancel, None, dict(tags=["Funding"], summary="Stop a monthly premium", request=None,
                                         responses=OBJ)),
    (payments.paypal_webhook, None, dict(tags=["Webhooks"], summary="PayPal webhook (signature-verified)",
                                         request=OBJ, responses=OBJ)),
    (payments.paypal_config, None, dict(tags=["Health"], summary="Public PayPal client id and JS SDK address",
                                        responses=OBJ)),

    (mandates.requests_, ["GET"], dict(
        tags=["Requests"], summary="Requests, newest first (inbox=1: waiting for this funder)",
        parameters=[OpenApiParameter("inbox", OpenApiTypes.BOOL), OpenApiParameter("status", OpenApiTypes.STR),
                    OpenApiParameter("mandate", OpenApiTypes.UUID)],
        responses=RequestSerializer(many=True))),
    (mandates.requests_, ["POST"], dict(
        tags=["Requests"], summary="Ask to spend: fraud check, then the rules decide (never pays by itself)",
        request=body("RequestInput", mandate=uuid(), product=text(), amount=money(required=False), beneficiary=uuid(required=False),
                     payee=uuid(required=False), message_text=text(required=False),
                     uploads=upload_refs(), idempotency_key=text(required=False),
                     basket_id=text(required=False, help_text="Order a basket from the payee's price list"),
                     fulfilment=s.ChoiceField(Request.FULFILMENTS, required=False)),
        responses=RequestDetailSerializer)),
    (mandates.request_detail, None, dict(tags=["Requests"], summary="Evidence, risk, decisions and payout",
                                         responses=RequestDetailSerializer)),
    (mandates.request_approval, None, dict(
        tags=["Requests"], summary="A funder's answer to an escalation or fraud hold",
        request=body("ApprovalInput", action=s.ChoiceField(["APPROVE", "REJECT", "VERIFIED_SAFE", "REPORT_FRAUD"]),
                     note=text(required=False)),
        responses=RequestDetailSerializer)),
    (mandates.uploads, None, dict(tags=["Requests"], summary="Upload a photo of a quote, invoice or progress",
                                  request={"multipart/form-data": body("UploadInput", file=s.FileField())},
                                  responses=OBJ)),
    (mandates.upload_file, None, dict(tags=["Requests"], summary="Download an upload", responses=OpenApiTypes.BINARY)),
    (mandates.ledger, None, dict(
        tags=["Requests"], summary="Append-only audit trail",
        parameters=[OpenApiParameter("mandate", OpenApiTypes.UUID), OpenApiParameter("request", OpenApiTypes.UUID)],
        responses=LedgerEntrySerializer(many=True))),

    (agent.conversations, None, dict(tags=["Assistant"],
                                     summary="Conversations (phone=...: talk as that number, DEMO_MODE only)",
                                     request=body("ConversationInput", phone=text(required=False)), responses=OBJ)),
    (agent.messages, None, dict(tags=["Assistant"], summary="Read or send a message to the AI agent",
                                request=body("MessageInput", text=text(required=False),
                                             upload_ids=s.ListField(child=uuid(), required=False)),
                                responses=OBJ)),

    (mandates.dashboard_data, None, dict(tags=["Dashboard"], summary="Tables for the AG Studio dashboard",
                                         responses=OBJ)),
    (mandates.dashboard_layout, None, dict(tags=["Dashboard"], summary="The family's saved dashboard layout",
                                           request=body("LayoutInput", state=s.DictField()), responses=OBJ)),
    (mandates.dashboard_summary, None, dict(tags=["Dashboard"], summary="Headline numbers", responses=OBJ)),
    (agent.dashboard_turn, None, dict(tags=["Dashboard"], summary="One AG Studio agent turn, answered server-side",
                                      request=OBJ, responses=OBJ)),

    (mandates.payee_upload_link, ["POST"], dict(
        tags=["Payee upload link"], summary="Get a payee's private upload link (new: true replaces the secret)",
        request=body("PayeeLinkInput", new=s.BooleanField(required=False)), responses=OBJ)),
    (mandates.payee_upload_link, ["DELETE"], dict(tags=["Payee upload link"], summary="Turn a payee's upload link off",
                                                  request=None, responses=OBJ)),
    (mandates.public_payee, None, dict(
        tags=["Payee upload link"], summary="Public: what the payee sees (what to send, how their requests are going)",
        auth=[], responses=OBJ)),
    (mandates.public_payee_send, None, dict(
        tags=["Payee upload link"], summary="Public: send a quote, invoice or photo (a new request, or a file for an "
                                            "open one); it can only ever pay this payee",
        auth=[], request={"multipart/form-data": body(
            "PayeeSendInput", file=s.FileField(), kind=s.ChoiceField(["QUOTE", "INVOICE", "MILESTONE_PHOTO"]),
            mandate=uuid(required=False), amount=money(required=False), note=text(required=False),
            request=uuid(required=False), idempotency_key=text(required=False))},
        responses=OBJ)),

    (mandates.beneficiary_shop_link, ["POST"], dict(
        tags=["Shop link"], summary="Get a beneficiary's private shop link (new: true replaces the secret)",
        request=body("ShopLinkInput", new=s.BooleanField(required=False)), responses=OBJ)),
    (mandates.beneficiary_shop_link, ["DELETE"], dict(tags=["Shop link"], summary="Turn a shop link off",
                                                      request=None, responses=OBJ)),
    (mandates.public_shop, None, dict(
        tags=["Shop link"], summary="Public: the store's price list, who can be asked to pay, recent shopping",
        auth=[], responses=OBJ)),
    (mandates.public_shop_order, None, dict(
        tags=["Shop link"], summary="Public: send a shopping list (paid from the fund, or invoiced to the family "
                                    "when the fund is short)", auth=[],
        request=body("ShopOrderInput", mandate=uuid(), store=uuid(required=False),
                     items=s.ListField(child=s.DictField()), fulfilment=s.ChoiceField(["COLLECT", "DELIVERY"]),
                     ask=text(required=False), note=text(required=False), idempotency_key=text(required=False)),
        responses=OBJ)),
    (mandates.public_shop_unlock, None, dict(
        tags=["Shop link"], summary="Public: enter the PIN the family gave (5 wrong tries turn the link off)",
        auth=[], request=body("ShopUnlockInput", pin=text()), responses=OBJ)),
    (payments.payee_paypal_login, None, dict(
        tags=["Payee upload link"], summary="Public: go to Log in with PayPal (the payee's own account unlocks the link)",
        auth=[], responses={302: None})),
    (payments.payee_logout, None, dict(tags=["Payee upload link"], summary="Public: forget the PayPal login",
                                       auth=[], request=None, responses=OBJ)),
    (mandates.public_business, None, dict(
        tags=["Landing page"], summary="Public: the families a business logged in with PayPal can send invoices to",
        auth=[], responses=OBJ)),
    (payments.business_login, None, dict(tags=["Landing page"], summary="Public: a business logs in with PayPal",
                                         auth=[], responses={302: None})),
    (payments.business_logout, None, dict(tags=["Landing page"], summary="Public: forget the business login",
                                          auth=[], request=None, responses=OBJ)),
    (mandates.public_home, None, dict(
        tags=["Landing page"], summary="Public: open a shop with the registered phone number and the family's PIN",
        auth=[], request=body("HomeAccessInput", phone=text(), pin=text()), responses=OBJ)),
    (agent.public_assistant, None, dict(
        tags=["Landing page"], summary="Public: the Hukama guide (no tools, no family data, 30 questions an hour)",
        auth=[], request=body("PublicAssistantInput", messages=s.ListField(child=s.DictField())), responses=OBJ)),
    (payments.invoice_create_order, None, dict(
        tags=["Shop link"], summary="A funder starts paying a shopping list with PayPal", request=None,
        responses=OBJ)),
    (payments.invoice_capture, None, dict(
        tags=["Shop link"], summary="Capture a funder's payment for a shopping list (the first one pays it)",
        request=body("InvoiceCaptureInput", order_id=text()), responses=RequestDetailSerializer)),
    (mandates.notifications, None, dict(tags=["Family"], summary="My notifications", responses=OBJ)),
    (mandates.notifications_read, None, dict(tags=["Family"], summary="Mark my notifications read", request=None,
                                             responses=OBJ)),

    (payments.demo_collect, None, dict(tags=["Demo"], summary="Mark cash collected (simulated last mile)",
                                       request=body("CollectInput", code=text(required=False)), responses=OBJ)),
]


def annotate():
    for view, methods, kwargs in ANNOTATIONS:
        extend_schema(methods=methods, **kwargs)(view)
