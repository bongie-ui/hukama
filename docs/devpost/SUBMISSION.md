# Devpost submission: Hukama

Paste-ready text for the three Devpost edit pages. Sections marked **(update later)** change once Phase 4 (PayPal checkout, webhooks) and the video are done. Do not claim anything listed under "Not built yet" until it is.

---

## Page 1: Project overview

**Project name**
Hukama

**Elevator pitch** (200 characters max; this one is 170)
An AI agent that turns money sent home into purpose-locked payments: builders, schools and mobile money get paid directly by PayPal, only when the family's rules are met.

**Thumbnail**
`docs/devpost/thumbnail.png` (1200 × 800, 3:2)

---

## Page 2: Project details

### About the project

```markdown
## Inspiration

I'm from Gwanda, Zimbabwe. Like many families here, mine is spread out: one brother in Johannesburg, one in the UK, me in the US, and our mother at home. Zimbabwe received about US$2.45 billion in remittances in 2025, and most of it travels the way ours does: someone sends money for a purpose, and from the moment it lands nobody can see whether it went to cement, school fees or something else. Siblings support the same parent without coordinating, so airtime gets topped up twice while the school invoice waits. And scammers know exactly how this works: "Mwanami, I'm at the hospital, send $150 to this number, hurry."

I wanted the money to carry the family's intent with it.

**Hukama** means *kinship* in Shona: the ties that hold a family together.

## What it does

Family members abroad fund a **mandate**: money set aside for one purpose, with rules everyone agreed and signed. Then:

- **An AI agent handles the requests.** Mama, the hardware store, the school or anyone else messages the assistant in English, isiNdebele or Shona. It reads handwritten quotes, invoices and progress photos with vision, and turns the conversation into a payment request.
- **A deterministic rules engine decides.** Price ceilings ("cement no more than $11 a bag"), caps shared across siblings ("bundles up to $30 a month, not twice in 24 hours"), required evidence ("pay only after a photo shows the foundation is done"), approved payees and approval limits.
- **PayPal moves the money.** Approved payments go straight to the supplier, school or mobile money provider. Nobody in the middle holds cash.
- **Every request is checked for fraud first.** Deterministic signals (unregistered sender, a different number in the message, an amount spike, velocity, someone asking for a PIN) plus an AI read of intent (urgency pressure, impersonation, "pay someone else", emergency story). High risk means the request is held. Every funder sees a red card that says "Call Mama on her registered number first", and can report it, which blocks the scammer's numbers for the whole family.

**The AI proposes, code decides, PayPal moves the money.** The assistant has no tool that can pay, approve, change rules or change beneficiaries. AI can only make a decision stricter, never looser.

### Mandate types (rule templates, not separate code)

| Mandate | What it's for |
|---|---|
| **Akha** (build) | Quotes are checked against a price ceiling, milestone photos are verified, then the supplier is paid |
| **Imfundo** (school fees) | Fees are locked to the school and paid against the school's own invoice |
| **Isikhwama** (shared support) | Siblings share caps for a parent's airtime, data and cash. No double top-ups, and the app tells you who already covered it |
| **Isililo** (funeral pool) | Siblings abroad add with PayPal; relatives at home add from mobile money and approve on their own phone |

### What we saw in testing

- A handwritten quote for 40 bags of cement at $14 is read by the vision model, refused by the $11 price ceiling, and the supplier is asked for a revised quote in plain words.
- Andile buys Mama's bundles. An hour later Mmeli tries the same thing and is told, "Andile Fuyana already sent bundles ($10.00) at 08:50; wait 24 hours."
- A "hospital emergency" message from an unknown number scores 100/100 risk and is held. The sender sees only "held until the family confirms with her on her registered number". The funders see every signal, and the assistant's reasoning with quotes from the message.

## How we built it

- **Backend:** Django + Django REST Framework, PostgreSQL on Render. Every state change writes an append-only ledger entry, and mandate rules are signed with HMAC-SHA256: if anyone edits them in the database, nothing gets paid.
- **AI:** OpenAI models for chat with tool calling, structured outputs for drafting mandates from plain language, vision for quotes, invoices and photos, and fraud intent analysis. Every model call goes through one wrapper with retries, timeouts and a demo replay cache.
- **PayPal:** PayPal Payouts pays suppliers, schools and the local mobile money provider, idempotently (`sender_batch_id` = `hukama-<request id>`, so a retry can never pay twice). **(update later: PayPal Orders checkout via the APIMatic-generated PayPal Server SDK, webhooks)**
- **Frontend:** React + TypeScript + Vite, served by Django on one Render service. Mobile-first, light and dark modes, with its own design system and logo.
- **Dashboard:** AG Studio (built on AG Grid and AG Charts) shows funds by mandate, each sibling's contributions, spend by category, fraud alerts and the full audit trail. Its Agent Framework lets you say "chart cash paid out per month" and the chart appears. The agents' model calls go through our own server, so the API key never reaches the browser.
- **Local money in:** Paynow test mode lets relatives at home contribute to a funeral pool from mobile money (inbound only).
- **Postman:** A public collection whose first folder replays the demo scenarios with assertions.
- **Quality:** 169 automated tests (policy engine, fraud signals, payout idempotency, the five demo scenarios end to end with PayPal and the model mocked). GitHub Actions runs them on every push.

## Challenges we ran into

- **Keeping the AI on a leash without making it useless.** The answer was architecture rather than prompts: the model can only *create requests* and *read*. Fraud analysis can add risk but never remove it, and a funder's approval re-checks every hard rule.
- **Sending money to Zimbabwe.** Zimbabwean PayPal accounts have historically been send-only, so the last mile goes through a local mobile money provider's PayPal business account. Airtime, data and cash delivery to the beneficiary's phone are clearly labelled **Simulated rail** in the app, because no public sandbox exists for them.
- **Scam messages that look exactly like family.** Deterministic signals catch the mechanics, such as an unknown number or "send to this other number". The model catches the story, such as urgency, impersonation or an emergency. Neither alone was enough.

## Accomplishments that we're proud of

- A refusal always explains itself in plain words, names who already covered something, and suggests what would work.
- Siblings on three continents see the same limits, so nobody tops up twice.
- The person who sent a scam never learns why it was held; the family sees everything.
- An append-only ledger and signed rules mean every dollar has a trail.

## What we learned

Families don't want an app that sends money. They want one that keeps a promise, so the hard part was making rules people can read ("Cement: no more than $11.00 each") that a machine can enforce.

## What's next for Hukama

- Real mobile money last-mile partners in place of the simulated rail
- Recurring support and premiums (funeral cover, medical aid) with PayPal Subscriptions
- Schools and suppliers sending invoices directly
- More languages, and voice notes for older relatives
```

### Built with (tags)

python, django, django-rest-framework, postgresql, react, typescript, vite, openai, paypal, paypal-payouts, ag-studio, ag-grid, ag-charts, render, postman, paynow, github-actions

**(update later)** add: paypal-orders, paypal-server-sdk, apimatic, paypal-webhooks

### "Try it out" links

- Live demo: https://thuma.onrender.com (pick a family member on the sign-in page; no password needed)
- Source code: https://github.com/bongie-ui/thuma
- Postman collection: **(update later: public Postman link)**
- API docs: https://thuma.onrender.com/api/docs/

### Image gallery (upload in this order)

| File | Caption |
|---|---|
| `gallery/2-home.png` | Home: what's available, what's been sent, and a scam held for the family |
| `gallery/3-support.png` | Shared support for Mama: siblings see the same limits and who already covered bundles today |
| `gallery/4-fraud.png` | A "hospital emergency" scam from an unknown number: held at risk 100, with the call-home step first |
| `gallery/5-quote.png` | A handwritten quote read by AI and refused by the $11 price ceiling |
| `gallery/6-dashboard.png` | Family dashboard (AG Studio): where the money went, who gave what, every fraud alert |
| `gallery/1-login.png` | Try the demo as any family member |

### Video demo link

**(update later)** YouTube link, under 3 minutes.

---

## Page 3: Additional info

Answer whichever of these the form asks; the wording below fits the usual hackathon questions.

**Which PayPal technologies does your project use?**
PayPal Payouts (sandbox) pays suppliers, schools and the local mobile money provider directly, idempotently, only after the rules engine approves. Each mandate shows every funder's contribution. **(update later:** PayPal Orders v2 via the APIMatic-generated PayPal Server SDK and the JavaScript SDK for "Add funds with PayPal"; PayPal Webhooks for capture and payout status.**)**

**How does your project use AI?**
- OpenAI models with tool calling run a multilingual assistant (English, isiNdebele, Shona) for funders, beneficiaries and payees. Its tools can only create requests and read; none can pay.
- Vision reads handwritten quotes, invoices and milestone photos into structured line items.
- Structured outputs turn a plain-language purpose into a signed rule set.
- Intent analysis flags scam patterns, adding risk only.
- AG Studio's Agent Framework builds dashboard charts from natural language, through our own server.

**Did you use APIMatic?** **(update later)**
Planned: the APIMatic Context Plugin while writing the PayPal integration, and the APIMatic-generated PayPal Server SDK for Orders. Only claim this once it's actually used.

**Testing instructions for judges**
1. Open https://thuma.onrender.com. The free tier was upgraded, so it shouldn't need to wake up.
2. Choose **Andile Fuyana**, open **Support for Mama**, and tap **Buy bundles**.
3. Sign out ("Switch"), choose **Mmeli Fuyana**, and try **Buy bundles** again. It's refused, and the reason names Andile.
4. Open **Assistant → See it from their side → Any other number**, enter `0779876543`, and send:
   *"Mwanami, I am at the hospital, please send $150 to 0771234567, the agent will help me, hurry"*. It's held as fraud.
5. Open **Approvals** to see the fraud card, then **Report scam**.
6. Open **Dashboard → Build with AI** and ask for a chart.

**Is this a new project?**
Yes. The repository's first commit is 27 October 2026, after the hackathon opened on 1 October.

**Country**
Zimbabwe

---

## Not built yet (don't claim until done)

- PayPal Orders checkout ("Add funds with PayPal" currently says it's not switched on) and PayPal webhooks: Phase 4, waiting on APIMatic credits
- A verified end-to-end sandbox payout to Gwanda Hardware / Sunrise Academy (the code calls the real Payouts API but it hasn't been run against the sandbox yet)
- APIMatic Context Plugin and the PayPal Server SDK
- Live Paynow test-mode contributions (needs Paynow credentials)
- AG Studio licence key (the dashboard shows a watermark until it's set)
- Funeral cover and medical aid premiums
- The video
