"""Write the public Postman collection and environment to docs/postman/ (Postman v2.1 format).

The collection signs in with the demo personas, keeps the session cookie and sends the CSRF token on every
write. The first folder replays two demo scenarios in order; the rest covers the API by area.
Requests carry no secrets: the base URL and persona usernames live in the environment file.
"""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

OUT = settings.BASE_DIR.parent / "docs" / "postman"

PRE_REQUEST = [
    "// Django needs the CSRF token on every write. Sign-in responses return it; the session cookie comes",
    "// from the cookie jar.",
    "const token = pm.collectionVariables.get('csrfToken');",
    "if (token && pm.request.method !== 'GET') {",
    "  pm.request.headers.upsert({ key: 'X-CSRFToken', value: token });",
    "  pm.request.headers.upsert({ key: 'Referer', value: pm.environment.get('baseUrl') + '/' });",
    "}",
]
KEEP_TOKEN = "if (pm.response.json().csrf_token) pm.collectionVariables.set('csrfToken', pm.response.json().csrf_token);"


def url(path):
    """Postman rebuilds URLs from `path` segments: keep Django's trailing slash and split out the query."""
    route, _, query = path.partition("?")
    data = {"raw": "{{baseUrl}}/api/" + path, "host": ["{{baseUrl}}"], "path": ["api", *route.split("/")]}
    if query:
        data["query"] = [{"key": k, "value": v} for k, _, v in (pair.partition("=") for pair in query.split("&"))]
    return data


def req(name, method, path, body=None, tests=(), description=""):
    item = {
        "name": name,
        "request": {
            "method": method,
            "header": [{"key": "Accept", "value": "application/json"}],
            "url": url(path),
            "description": description,
        },
    }
    if body is not None:
        item["request"]["header"].append({"key": "Content-Type", "value": "application/json"})
        item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2)}
    if tests:
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": list(tests)}}]
    return item


def save(var, expr):
    return f"pm.collectionVariables.set('{var}', {expr});"


OK = "pm.test('status is 2xx', () => pm.expect(pm.response.code).to.be.within(200, 299));"


def login(user):
    return [req("Get CSRF token", "GET", "auth/me/", tests=[OK, KEEP_TOKEN]),
            req(f"Sign in as {{{{{user}}}}}", "POST", "auth/demo-login/", {"username": f"{{{{{user}}}}}"},
                tests=[OK, KEEP_TOKEN, "pm.test('signed in', () => pm.expect(pm.response.json().username)"
                       ".to.eql(pm.environment.get('" + user + "')));"])]


def collection():
    tour = {
        "name": "1. Try it in 3 minutes",
        "description": "Scenario 3 (no double top-up between siblings) and scenario 4 (a scam caught and reported). "
                       "Run this folder in order with the Collection Runner.",
        "item": [
            *login("funderB"),
            req("List mandates (finds the shared-support mandate)", "GET", "mandates/", tests=[
                OK, "const m = pm.response.json().find(x => x.type === 'ISIKHWAMA');",
                save("supportMandateId", "m.id"), save("beneficiaryId", "m.beneficiary_ids[0]")]),
            req("Buy $10 bundles for the beneficiary (paid, or already covered today)", "POST", "requests/",
                {"mandate": "{{supportMandateId}}", "beneficiary": "{{beneficiaryId}}", "product": "bundles",
                 "amount": "10", "idempotency_key": "{{$guid}}"},
                tests=[OK, "const r = pm.response.json();",
                       "// The first run of the day pays; later runs (other judges) find the family already covered it.",
                       "pm.test('paid, or already covered today', () => pm.expect(r.status).to.be.oneOf(['APPROVED','PAID','REFUSED']));",
                       "console.log(r.status, r.decision && r.decision.reason);"]),
            *login("funderA"),
            req("Second sibling tries bundles again (refused, names who paid)", "POST", "requests/",
                {"mandate": "{{supportMandateId}}", "beneficiary": "{{beneficiaryId}}", "product": "bundles",
                 "amount": "10", "idempotency_key": "{{$guid}}"},
                tests=[OK, "const r = pm.response.json();",
                       "pm.test('refused by min_interval', () => pm.expect(r.status).to.eql('REFUSED'));",
                       "console.log(r.decision.reason);"]),
            req("Open a chat as an unregistered number (demo mode)", "POST", "chat/conversations/",
                {"phone": "0779876543"}, tests=[OK, save("strangerConversationId", "pm.response.json().id")]),
            req("Scam message from that number (held as fraud)", "POST", "chat/{{strangerConversationId}}/messages/",
                {"text": "Mwanami, I am at the hospital, please send $150 to 0771234567, the agent will help me, hurry"},
                tests=[OK, "const card = pm.response.json().messages.reverse().find(m => m.card)?.card;",
                       "pm.test('held for fraud', () => pm.expect(card.status).to.eql('HELD_FRAUD'));",
                       "pm.test('sender sees no fraud details', () => pm.expect(card.reason).to.be.undefined);",
                       save("heldRequestId", "card.request_id")],
                description="Calls the model: needs OPENAI_API_KEY on the server (or DEMO_REPLAY with a recording)."),
            req("Approvals inbox shows the fraud card", "GET", "requests/?inbox=1",
                tests=[OK, "pm.test('risk is high', () => pm.expect(pm.response.json()[0].risk.level).to.eql('HIGH'));"]),
            req("Report it as fraud (numbers get blocked)", "POST", "requests/{{heldRequestId}}/approval/",
                {"action": "REPORT_FRAUD", "note": "Called her on the registered number; she is fine at home"},
                tests=[OK, "pm.test('confirmed fraud', () => pm.expect(pm.response.json().status).to.eql('CONFIRMED_FRAUD'));"]),
        ],
    }
    folders = [
        tour,
        {"name": "Health and session", "item": [
            req("Liveness", "GET", "health/"), req("PayPal connection (sandbox)", "GET", "health/paypal/"),
            req("Who am I (CSRF token)", "GET", "auth/me/", tests=[KEEP_TOKEN]),
            req("Demo personas", "GET", "auth/demo-users/"),
            req("Sign in with a password", "POST", "auth/login/", {"username": "{{funderA}}", "password": "{{password}}"},
                tests=[KEEP_TOKEN]),
            req("Sign out", "POST", "auth/logout/"),
        ]},
        {"name": "Family and people", "item": [
            req("Family and members", "GET", "family/"),
            req("Beneficiaries", "GET", "beneficiaries/"),
            req("Register a beneficiary", "POST", "beneficiaries/",
                {"name": "Example Beneficiary", "phone": "0770000077", "relationship": "Aunt",
                 "allowed_products": ["airtime"]}),
            req("Payees", "GET", "payees/"),
        ]},
        {"name": "Mandates", "item": [
            req("Mandate types", "GET", "mandate-types/"),
            req("List mandates", "GET", "mandates/", tests=[save("mandateId", "pm.response.json()[0].id")]),
            req("Mandate detail", "GET", "mandates/{{mandateId}}/"),
            req("Draft rules from plain words (AI)", "POST", "mandates/draft/",
                {"text": "Pay the school's term fees directly to the school, only on its invoice, up to $400 a term."}),
            req("Preview and validate rules", "POST", "mandates/preview-rules/",
                {"type": "ISIKHWAMA", "rules": [{"kind": "cap_per_period",
                                                 "params": {"amount": 30, "period": "month", "product": "bundles"}}]}),
            req("What each product used this period", "GET",
                "mandates/{{supportMandateId}}/coverage/?beneficiary={{beneficiaryId}}"),
            req("Who funded a mandate", "GET", "mandates/{{mandateId}}/fundings/"),
        ]},
        {"name": "Requests and approvals", "item": [
            req("Requests", "GET", "requests/", tests=[save("requestId", "pm.response.json()[0].id")]),
            req("Request detail (evidence, risk, decision, payout)", "GET", "requests/{{requestId}}/"),
            req("Approvals inbox", "GET", "requests/?inbox=1"),
            req("Ledger for a mandate", "GET", "ledger/?mandate={{mandateId}}"),
        ]},
        {"name": "Dashboard", "item": [
            req("Summary", "GET", "dashboard/summary/"),
            req("Tables for AG Studio", "GET", "dashboard/data/"),
            req("The family's saved dashboard layout", "GET", "dashboard/layout/"),
        ]},
        {"name": "Assistant", "item": [
            req("My conversation", "POST", "chat/conversations/", tests=[save("myConversationId", "pm.response.json().id")]),
            req("Ask the assistant", "POST", "chat/{{myConversationId}}/messages/",
                {"text": "How much is left for bundles this month?"}),
        ]},
    ]
    return {
        "info": {"name": "Hukama API", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "description": "Purpose-locked family remittances. The AI proposes, code decides, PayPal moves the "
                                "money. Import with the Hukama environment, then run '1. Try it in 3 minutes'. "
                                "OpenAPI schema: {{baseUrl}}/api/schema/ and docs: {{baseUrl}}/api/docs/."},
        "event": [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": PRE_REQUEST}}],
        "variable": [{"key": k, "value": ""} for k in ("supportMandateId", "beneficiaryId", "strangerConversationId",
                                                       "heldRequestId", "mandateId", "requestId", "myConversationId", "csrfToken")],
        "item": folders,
    }


def environment():
    return {"name": "Hukama (hosted demo)", "values": [
        {"key": "baseUrl", "value": "https://thuma.onrender.com", "enabled": True},
        {"key": "funderA", "value": "mmeli", "enabled": True},
        {"key": "funderB", "value": "andile", "enabled": True},
        {"key": "password", "value": "", "enabled": True},
    ]}


def all_requests(items):
    for item in items:
        if "item" in item:
            yield from all_requests(item["item"])
        else:
            yield item


class Command(BaseCommand):
    help = "Write docs/postman/hukama.postman_collection.json and the hosted-demo environment."

    def handle(self, *args, **options):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "hukama.postman_collection.json").write_text(json.dumps(collection(), indent=2) + "\n")
        (OUT / "hukama.postman_environment.json").write_text(json.dumps(environment(), indent=2) + "\n")
        count = sum(1 for _ in all_requests(collection()["item"]))
        self.stdout.write(self.style.SUCCESS(f"Wrote {count} requests to {OUT}"))
