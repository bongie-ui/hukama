# CLAUDE.md — Hukama

Context file for Claude Code (terminal or claude.ai/code on the web). Read this first. **`BUILD_SPEC.md`** (repo root) has the detailed build plan, data model, phases and acceptance tests; when the two disagree, BUILD_SPEC wins on implementation detail and this file wins on product rules. The full log of what was built, verified and fixed is in **`docs/HISTORY.md`**.

## What we're building

**Hukama** ("kinship" in Shona; renamed from Thuma on 2 Nov) — purpose-locked diaspora remittances. Family members abroad fund **mandates** (signed rules for how money may be spent). An **AI agent** handles requests from family, suppliers and schools, reads quotes/invoices/photos, flags possible fraud, and proposes payments. A deterministic **policy engine** decides. **PayPal** moves the money.

Built for the **PayPal AI Hackathon** (Devpost). Builder: Bonginkosi, Gwanda, Zimbabwe. Submit by **11 Nov 2026** (deadline 12 Nov, 12:00 PT = 21:00 Harare).

**Elevator pitch:** An AI agent that turns diaspora remittances into purpose-locked payments, paying builders, undertakers and insurers directly, only when the rules you set are met.

**Problem:** Zimbabwe received ~US$2.45bn in remittances in 2025 (RBZ). Money sent for a purpose loses the sender's control once it lands; siblings abroad support the same parent without coordinating; mobile money scams (impersonation, fake emergencies, "send to this number") target exactly these families. Zimbabwean PayPal accounts have historically been send-only, so the last mile is hard.

## Mandate types

| Type | Purpose | Status |
|---|---|---|
| **Akha** (Build) | Agent checks quotes (price ceiling) + milestone photos, pays the supplier | Built |
| **Imfundo** (School fees) | Fees locked to a school; paid on the school's invoice | Built |
| **Isikhwama** (Shared support for a parent) | Several funders share caps for airtime, bundles, cash and groceries (collect or home delivery); no double top-ups | Built |
| **Isililo** (Funeral) | Funeral pool funded by the family and anyone with the pool's PayPal link | Built |
| **Vikela** (Cover) | Funeral cover / medical aid premiums by PayPal Subscriptions | Built |

Mandate types are **rule templates + data** (`mandates/templates.py`), not separate code paths.

## Fraud flagging

Every request is risk-assessed **before** the policy engine (`agent/fraud.py`):
1. **Deterministic signals** (always run): unregistered sender, a different phone number in the message, beneficiary number or delivery address recently changed, amount spike, velocity, odd hours, PIN/OTP mentioned, previously reported number.
2. **LLM intent analysis**: urgency pressure, impersonation, third-party payment, emergency story, credential request, reversal scam, prize scam, style mismatch, purpose mismatch — with reasons, quotes and a verification step.

HIGH risk → **HOLD_FRAUD**: a funder must call the beneficiary on the **registered** number and confirm, or report fraud. MEDIUM → a funder must approve. **AI can only add risk, never remove it** (a re-check keeps the higher score).

## Core rules — never break these

1. **The AI proposes, code decides, PayPal moves the money.** No LLM tool can pay, approve, change rules or change beneficiaries.
2. **AI can only make things stricter.**
3. **Nothing about the demo family is hard-coded.** The Fuyana family exists only in `seed_demo`. Code, prompts and UI are generic; tests use generic data (`core/testing.py`).
4. **PayPal is central in every flow.** All funding via PayPal; all real payouts are PayPal Payouts. Simulated rails are labelled "Simulated rail" in the UI.
5. **Consult the APIMatic Context Plugin** (MCP `context-matic`, `/plugin install context-matic@apimatic`) before writing or changing PayPal code. If it isn't available in the session (e.g. on the web), say so before touching PayPal calls in `payments/`; the guidelines it installed are in `.claude/`.
6. **No third-party brand names/logos** in UI or video. Use neutral labels.
7. **Only verified payees can be paid**, and every payout goes through fraud → policy → `Rail` (never directly).

## Working on the web (claude.ai/code) or a fresh clone

The cloud session clones `github.com/bongie-ui/hukama` with no `.env`, no local database and no installed packages.

**Setup** (Python 3.13+, CI uses 3.13; Node 22):
```bash
cd backend && pip install -r requirements.txt && python manage.py migrate && python manage.py seed_demo
cd ../frontend && npm ci && npm run build      # Django serves frontend/dist
```
Run the app: `cd backend && python manage.py runserver` → http://localhost:8000 (the demo persona login needs `DEMO_MODE=true`).

**Before every commit** (the same checks CI runs):
```bash
cd backend && python manage.py test && python manage.py makemigrations --check --dry-run
cd ../frontend && npx tsc --noEmit -p . && npm run build
```
Tests never call PayPal or OpenAI (`settings.TESTING` blanks the keys), so they pass with no secrets. CI also runs them on PostgreSQL 16, which rejects some row locks SQLite ignores.

**Secrets** are read from a repo-root `.env` locally (template: `.env.example`) or from environment variables. On the web, set them in the environment's settings, never in a committed file:
- None are needed for code, tests, or the demo with rules-only fraud checks.
- `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-5.5-2026-04-23`, `OPENAI_MODEL_FAST=gpt-5.4-mini-2026-03-17`: AI drafting, reading documents, fraud intent, chat.
- `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com` (not the website URL): real sandbox checkout and payouts; also needed for `register_webhook`.
- `MANDATE_SIGNING_KEY`: any long random string locally. Changing it invalidates every mandate signature (`seed_demo --reset` rebuilds).
- `DEMO_MODE=true` for the persona switcher and "talk as…" chat.

If calls to `api-m.sandbox.paypal.com`, `api.openai.com` or `thuma.onrender.com` fail from a web session, its network access must allow those domains.

**Deploying:** Render auto-deploys **`main`** (`render.yaml`; `build.sh` runs pip, the frontend build, collectstatic, migrate, and `seed_demo --sync` when `DEMO_MODE=true`). Web sessions usually push a `claude/…` branch, and nothing is live until it is merged into `main`. After deploying, check `https://thuma.onrender.com/api/health/paypal/` (should say `connected`) and run the Postman tour (below).

**Useful commands** (in `backend/`): `seed_demo [--reset|--if-missing|--sync]`, `export_postman` (regenerates `docs/postman/`), `register_webhook https://thuma.onrender.com` (after adding webhook event types), `poll_payouts`, `agent_chat` (talk to the agent in the terminal), `spectacular --validate --fail-on-warn` (OpenAPI).

## Repo map

| Path | What |
|---|---|
| `backend/thuma/` | Django project (settings `base/local/production`, `api_urls.py`, `api_schema.py` OpenAPI annotations) |
| `backend/accounts/` | Family, Membership (ADMIN / FUNDER / VIEWER), DashboardLayout, session + demo login |
| `backend/mandates/` | Models, `services.py` (every state change), `templates.py`, `signing.py`, REST views, dashboard tables, payee upload links |
| `backend/agent/` | `llm.py` (the only OpenAI import), `fraud.py`, `policy.py`, `chat.py` (7 tools, none can pay), `drafting.py`, `extraction.py`, prompts |
| `backend/payments/` | `paypal_client.py`, `checkout.py` (Orders via the Server SDK), `payouts.py`, `rails/`, `webhooks.py`, `premiums.py` (Subscriptions), `last_mile.py` (simulated) |
| `backend/core/` | BaseModel, phones, test fixtures, `seed_demo`, `export_postman`, SPA view |
| `backend/demo_assets/` | Quotes ($14, $10.50), foundation photo, Sunrise invoice (use the PNG; PDFs are not read) |
| `frontend/src/` | React 19 + Vite + TS, hash router. Pages include the public `Give.tsx` (`#/give/<token>`) and `Supplier.tsx` (`#/supplier/<token>`); `dashboard/` is AG Studio |
| `docs/` | `HISTORY.md`, `postman/`, `devpost/SUBMISSION.md` + gallery, `architecture.svg/png` |

## How the money flows (key facts)

- **Funding:** PayPal Orders v2 (CAPTURE) into the platform's business account (`platform@thuma.com`). A Funding counts only after a COMPLETED capture for the exact amount. Mandate balance = captured − refunded − approved/paid requests: Hukama's per-mandate record of money held in that one PayPal account.
- **Payouts:** PayPal Payouts with `sender_batch_id = hukama-<request id>` (idempotent). Status only moves forward; failed/returned are final. Mobile money = a real Payout to the provider + a simulated last mile (airtime/bundles delivered, cash code collected).
- **Webhooks** (`/api/webhooks/paypal/`, Render hook `6A597005RK7522420`): every event is verified with PayPal, stored and applied in one transaction, and deduped by event id. Handles captures, refunds/chargebacks, payout batch/item status, subscriptions and premium sales.
- **Concurrency:** decisions on one mandate are serialised (`services.lock_mandate`), so caps and the balance can't be double-spent.
- **Shop link and invoices:** a beneficiary picks items at `#/shop/<token>`; the fund pays first, and only an "insufficient funds" list that passes every other rule becomes an invoice (`INVOICED`) to the funders, settled by the first PayPal payment (`services.settle_invoice`).
- **Landing page ways in:** `#/business` (a business logs in with PayPal and sees the families it can invoice), `#/at-home` (registered phone + PIN opens the shop), and the Ask Hukama guide (no tools, no family data). The demo persona switcher offers only the seeded demo family.
- **Payee upload link:** a payee with no account sends invoices/quotes/photos at `#/supplier/<token>`; the request can only pay that payee and goes through the normal checks. Funders manage links on the People page.
- **Production caveat** (for the Devpost text): pooling family money in our own account is regulated; production would use PayPal's marketplace product with delayed disbursement.

## Demo cast (seed_demo only)

Sandbox accounts are all US PayPal accounts; story locations differ. Personas: `mmeli` (family admin), `bonginkosi`, `andile`.

| Name | Kind | Story |
|---|---|---|
| Thuma Platform (`platform@thuma.com`) | PayPal business | Our app; `thuma-platform` app credentials; sends all payouts |
| Mmeli Fuyana | PayPal personal | Son in Johannesburg (family admin) |
| Bonginkosi Fuyana | PayPal personal | Son in the United States |
| Andile Fuyana | PayPal personal | Son in the United Kingdom |
| Gwanda Hardware | PayPal business | Supplier, Gwanda |
| Sunrise Academy | PayPal business | School, Gwanda |
| Gwanda Fresh Market | PayPal business | Grocer (collect or delivery) |
| Local Mobile Money | PayPal business + simulated last mile | Mobile money provider, Zimbabwe |
| Mama Siqile Fuyana | Beneficiary (no PayPal) | Mother in Gwanda |
| Peaceful Rest Funeral Cover, Imbali Health Medical Aid | Simulated billers | Zimbabwe |

## Live resources

- App: https://thuma.onrender.com (Render paid plan until 2027, Postgres, Frankfurt). Health: `/api/health/`, `/api/health/paypal/`. API docs: `/api/docs/`.
- Repo: github.com/bongie-ui/hukama (CI: `.github/workflows/tests.yml`).
- Postman: public docs https://documenter.getpostman.com/view/43618475/2sBYHXRJVS; workspace "hukama" `2b62f875-6bf6-42c1-8281-3139e4778df7`, collection "Hukama API" `43618475-40822b34-8700-4fda-a1d5-1a7bba447496`. The repo keeps the v2.1 JSON (`docs/postman/`). To update the cloud copy: run `export_postman`, `postman workspace pull <workspace id>` into a scratch folder, `postman collection migrate` the JSON over the collection folder, `postman workspace diff`, then `postman workspace push` (needs `postman login`).
- Postman tour against Render: `npx newman@6.2.1 run docs/postman/hukama.postman_collection.json -e docs/postman/hukama.postman_environment.json --folder "1. Try it in 3 minutes"` (expect 11/11 requests, 19/19 assertions).

## Coding conventions

- PayPal code only in `payments/` (`paypal_client.py`, `checkout.py`, `premiums.py`, `rails/`); never from views.
- Every payout goes through the policy engine and the `Rail` interface. Internal names (Django package `thuma`, Render service `thuma`, `platform@thuma.com`) stay; only user-visible text says Hukama.
- Every state change writes an append-only `LedgerEntry`.
- Small, testable functions. Tests first for policy and fraud; add a test for every bug or loophole fixed.
- Never commit `.env`, sandbox passwords or real personal data (`thuma_sandbox_*` and `*.numbers` are gitignored).
- Ask before adding dependencies not listed in BUILD_SPEC.

## Current status (5 Nov 2026)

Phases 1–8 are done and verified live on Render with the real model and sandbox PayPal (279 tests, CI green). Details, batch ids and verifications are in `docs/HISTORY.md`.

- [x] Phases 1 Foundations · 2 Policy + fraud · 3 Render · 4 PayPal funding, payouts, mobile money rail, webhooks (built with the APIMatic plugin) · 5 Agent · 6 Frontend + seed_demo · 7 AG Studio dashboard, Isililo pool, Postman · 8 Hardening, README, OpenAPI
- [x] Extras: Hukama rebrand + redesign, funeral cover premiums (PayPal Subscriptions; live subscription `I-URGX2TF3YXPV` active), family invite, groceries, pool contribution link
- [x] 5 Nov loophole audit: unverified payees can't be paid, per-mandate locking, a funder's rejection can't be undone by a re-check, risk never lowered, address-change signal, refunds/chargebacks, forward-only payout status, atomic webhooks, premium dedupe, whole-cent amounts
- [x] 5 Nov payee upload link (schools/builders send invoices without an account); verified live (batch `N2QL9D63HU7W8`)
- [x] 6 Nov groceries by item; Mama's shop link (`#/shop/<token>`): the fund pays when it can, otherwise the list is invoiced to every son or the one she picks; the first to pay with PayPal covers it and the others are notified in the app
- [x] 6 Nov who is really asking: payee links need Log in with PayPal as the payee's own account; shop links need a PIN told by phone (5 wrong = off + family told; family notified of every list); "Start your family" sign-up; first-visit guided tour + Getting started checklist; upload-link box on the mandate page
- [x] **Phase 9 — Video + Devpost text** (11 Nov): video https://youtu.be/6DvEVSm4mjM (public, captioned); Devpost story, video link and README updated
- [ ] Phase 10 — Submitted (by 11 Nov)

**Open items that need the user's logins or decisions**
- Grocer sandbox password unknown (not in the Numbers sheet); reset it in the PayPal developer dashboard if needed
- Devpost: the video link is in (11 Nov); add the grocer password to the judges' notes yourself and press Submit. Story (with the home-page entries), tags, links, gallery, eligibility ticks and judges' notes are filled (7 Nov)
- Log in with PayPal verified live (7 Nov, batch `8SAH2QJRKF72J`); not yet tried live: the home page's Send an invoice login as `fees@business.example.com` (needs the user to type the password)
- GitHub About: description, website and topics set (7 Nov, via `gh`, logged in as bongie-ui); only the social preview image is left (Settings → Social preview → `docs/devpost/thumbnail.png`, browser only)
- The AG Studio licence is a 45-day trial key (`VITE_AG_STUDIO_LICENSE_KEY`, build-time)
- Known limits, not fixed: the mandate owner can change rules on a mandate others also fund (ledgered; money only goes to verified payees); public pool checkout has no rate limit; viewers can submit requests (the rules still decide); no WhatsApp/SMS channel (built, then removed on 7 Nov as out of scope)

## Working method for Claude Code

- One phase (or one clearly scoped task) per session: read, plan, build, test, then summarise what changed.
- After meaningful work: add a dated entry to `docs/HISTORY.md` and update "Current status" here (keep this file short).
- Verify on Render after deploying when the change touches money, webhooks or public pages.
