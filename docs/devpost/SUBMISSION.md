# Devpost submission: Hukama

Paste-ready text for the three Devpost edit pages. Sections marked **(update later)** change once the video exists. Do not claim anything listed under "Not built yet" until it is.

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
**Try it:** [live demo](https://thuma.onrender.com) (pick a family member, no password) · [guide for judges](https://github.com/bongie-ui/hukama/blob/main/docs/GUIDE.md) · [code](https://github.com/bongie-ui/hukama) · [API on Postman](https://documenter.getpostman.com/view/43618475/2sBYHXRJVS)

## Inspiration

Zimbabwe received about **US$2.45 billion** in diaspora remittances in 2025, more than 8% of GDP, and about **US$1.86 billion** in just the first eight months of 2026, up 22% ([The Zimbabwe Mail](https://thezimbabwemail.com/main-headline/zimbabwes-diaspora-remittances-rise-to-us2-45-billion-as-uk-overtakes-south-africa/), [The Herald](https://www.heraldonline.co.zw/diaspora-remittances-surge-22pc/)). The UK and South Africa are the biggest sources.

A lot of that money is sent **for a purpose**: school fees, cement for a house, groceries for a parent, a funeral. Yet:

- Once the money lands, the sender can't see whether it went to that purpose.
- Relatives in different countries support the same person without coordinating, so one thing gets paid twice while another waits.
- It's expensive: sending money to Sub-Saharan Africa costs about **8.5–9%** on average, the most of any region, against a UN target of 3% ([UN DESA](https://policy.desa.un.org/publications/world-economic-situation-and-prospects-november-2025-briefing-no-196)).
- Scammers target exactly these families with fake emergencies: *"I'm at the hospital, send $150 to this number, hurry."*

I'm from Gwanda, Zimbabwe, and I wanted to make sending money home **easy and safe**: pay the school, the builder or the shop directly, and only when the rules the family agreed are met.

To show how it works, Hukama comes with a **demo family**, the Fuyanas: three brothers in Johannesburg, the UK and the US supporting their mother in Gwanda. The family is fictional; the problem is real.

**Hukama** means *kinship* in Shona: the ties that hold a family together.

## What it does

Family members abroad fund a **mandate**: money set aside for one purpose, with rules everyone agreed and signed. Then:

- **An AI agent handles the requests.** The person at home (Mama, in the demo), the hardware store, the school or anyone else messages the assistant in English, isiNdebele or Shona. It reads handwritten quotes, invoices and progress photos with vision, and turns the conversation into a payment request.
- **A deterministic rules engine decides.** Price ceilings ("cement no more than $11 a bag"), caps shared across siblings ("bundles up to $30 a month, not twice in 24 hours"), required evidence ("pay only after a photo shows the foundation is done"), approved payees and approval limits.
- **PayPal moves the money.** Approved payments go straight to the supplier, school or mobile money provider. Nobody in the middle holds cash.
- **Schools, builders and shops don't need an account.** Each gets a private upload link. They log in with the PayPal account that receives the money, so only the business that gets paid can ask for it, then send a photo of the quote or invoice.
- **The people at home can ask for themselves.** In the demo, Mama gets her own shop link and picks groceries item by item. A PIN the family tells her on the phone proves it's her. If the support fund can pay, the shop is paid straight away. If it can't, her list goes to every son (or the one she picks). The first to pay with PayPal covers it, and the others are told.
- **Every request is checked for fraud first.** Deterministic signals (unregistered sender, a different number in the message, an amount spike, velocity, someone asking for a PIN) plus an AI read of intent (urgency pressure, impersonation, "pay someone else", emergency story). High risk means the request is held. Every funder sees a red card that says "Call Mama on her registered number first", and can report it, which blocks the scammer's numbers for the whole family.

**The AI proposes, code decides, PayPal moves the money.** The assistant has no tool that can pay, approve, change rules or change beneficiaries. AI can only make a decision stricter, never looser.

### Mandate types (rule templates, not separate code)

| Mandate | What it's for |
|---|---|
| **Akha** (build) | Quotes are checked against a price ceiling, milestone photos are verified, then the supplier is paid |
| **Imfundo** (school fees) | Fees are locked to the school and paid against the school's own invoice |
| **Isikhwama** (shared support) | Siblings share caps for a parent's airtime, data, cash and groceries. Groceries are chosen item by item from a local store's price list, collected in store or delivered to the registered address only. No double top-ups, and the app tells you who already covered it |
| **Isililo** (funeral pool) | The family funds it, and anyone with the pool's link can give with PayPal, no account needed |
| **Vikela** (cover) | Funeral cover (including repatriation for family abroad) or medical aid, paid monthly by PayPal Subscriptions to the named provider |

### What we saw in testing

- A handwritten quote for 40 bags of cement at $14 is read by the vision model, refused by the $11 price ceiling, and the supplier is asked for a revised quote in plain words.
- The revised quote at $10.50 plus the foundation photo is approved, and Gwanda Hardware receives a real $420 PayPal sandbox payout within half a minute. Sunrise Academy's $340 invoice is paid the same way, and a $48 grocery basket is paid to the store and delivered to Mama's registered address.
- Andile buys Mama's bundles. An hour later Mmeli tries the same thing and is told, "Andile Fuyana already sent bundles ($10.00) at 08:50; wait 24 hours."
- Sunrise Academy sends its invoice through its upload link. At $300 it's refused ("The invoice total ($340.00) does not match the request"); at $340 it's paid by PayPal Payout.
- Mama's shopping list is refused while Andile's groceries from 3 November are still inside the family's 72-hour rule, and she's told exactly why. Without her PIN her shop shows nothing but her first name. Five wrong guesses turn the link off and alert the family.
- A "hospital emergency" message from an unknown number scores 100/100 risk and is held. The sender sees only "held until the family confirms with her on her registered number". The funders see every signal, and the assistant's reasoning with quotes from the message.

## How we built it

- **Backend:** Django + Django REST Framework, PostgreSQL on Render. Every state change writes an append-only ledger entry, and mandate rules are signed with HMAC-SHA256: if anyone edits them in the database, nothing gets paid.
- **AI:** OpenAI models for chat with tool calling, structured outputs for drafting mandates from plain language, vision for quotes, invoices and photos, and fraud intent analysis. Every model call goes through one wrapper with retries, timeouts and a demo replay cache.
- **PayPal, end to end:** money comes in through **PayPal checkout** (Orders v2 via the APIMatic-generated **PayPal Server SDK**, **JS SDK v6** buttons), for funders and for anyone with a pool's link. Funeral cover (including repatriation for family abroad) is paid monthly by **PayPal Subscriptions**; each premium is recorded once and then passed to the cover provider by the rules. Money goes out by **PayPal Payouts** to suppliers, schools, the grocer and the local mobile money provider, idempotently (`sender_batch_id` = `hukama-<request id>`). **PayPal webhooks** update captures and payouts the moment they happen; every event is signature-verified with PayPal and applied once.
- **APIMatic:** the PayPal integration was written in Claude Code with the **APIMatic Context Plugin for PayPal**, which supplied the SDK's exact models, endpoints and idempotency parameters.
- **Frontend:** React + TypeScript + Vite, served by Django on one Render service. Mobile-first, light and dark modes, with its own design system and logo.
- **Dashboard:** AG Studio (built on AG Grid and AG Charts) shows funds by mandate, each sibling's contributions, spend by category, fraud alerts and the full audit trail. Its Agent Framework lets you say "chart cash paid out per month" and the chart appears. The agents' model calls go through our own server, so the API key never reaches the browser.
- **Links instead of accounts:** a funeral pool's link lets anyone give with PayPal. A payee's upload link uses **Log in with PayPal**: the logged-in PayPal email must be the account the payout goes to. A person at home gets a shop link opened with a PIN. Whatever arrives through a link can only pay that link's payee or the family's store, and still goes through the fraud check and the rules.
- **Invoices between siblings:** when the support fund can't cover a shopping list, it becomes an invoice to the family. The first son's PayPal payment is captured, the list is re-checked against every rule and the store is paid. A late second payment simply stays in the fund. Everyone sees in-app notifications.
- **Hardening:** an audit closed real loopholes. Only payees Hukama has verified can be paid. Decisions on one mandate are serialised so two siblings can't spend the same limit at once. Refunds and chargebacks reduce the balance. Payout status only moves forward, and webhooks are stored and applied in one transaction.
- **Onboarding:** anyone can start a new family. A first-visit tour and a "Getting started" checklist walk them to their first payment.
- **Postman:** A public workspace with the whole API (47 requests) and folders that replay the demo against the hosted app with assertions (18 requests, 28 checks, passing).
- **Quality:** 262 automated tests (every rule, fraud signals, payout idempotency, the loopholes, payee and shop links, invoices, and the five demo scenarios end to end with PayPal and the model mocked). GitHub Actions runs them on PostgreSQL on every push.

## Challenges we ran into

- **Keeping the AI on a leash without making it useless.** The answer was architecture rather than prompts: the model can only *create requests* and *read*. Fraud analysis can add risk but never remove it, and a funder's approval re-checks every hard rule.
- **Sending money to Zimbabwe.** Zimbabwean PayPal accounts have historically been send-only, so the last mile goes through a local mobile money provider's PayPal business account. Airtime, data and cash delivery to the beneficiary's phone are clearly labelled **Simulated rail** in the app, because no public sandbox exists for them.
- **Proving who is asking, without accounts.** Suppliers and schools already have PayPal, so Log in with PayPal proves the request comes from the account that gets paid. Mama has no PayPal, so her shop link needs a PIN the family tells her on a phone call, never in the same message as the link. The family is also told about every list paid from the fund.
- **Scam messages that look exactly like family.** Deterministic signals catch the mechanics, such as an unknown number or "send to this other number". The model catches the story, such as urgency, impersonation or an emergency. Neither alone was enough.

## Accomplishments that we're proud of

- A refusal always explains itself in plain words, names who already covered something, and suggests what would work.
- Siblings on three continents see the same limits, so nobody tops up twice.
- The person who sent a scam never learns why it was held; the family sees everything.
- An append-only ledger and signed rules mean every dollar has a trail.
- Mama can shop for herself, and her sons never pay for the same list twice.

## What we learned

Families don't want an app that sends money. They want one that keeps a promise, so the hard part was making rules people can read ("Cement: no more than $11.00 each") that a machine can enforce.

## What's next for Hukama

- Real mobile money last-mile partners in place of the simulated rail
- PayPal's marketplace product with delayed disbursement, so family money is held by PayPal for the payee rather than in the platform's own account (pooling it ourselves is regulated)
- WhatsApp and SMS: links, invoices and notifications where families already talk
- More languages, and voice notes for older relatives
```

### Built with (tags)

python, django, django-rest-framework, postgresql, react, typescript, vite, openai, paypal, paypal-payouts, ag-studio, ag-grid, ag-charts, render, postman, github-actions

paypal-orders, paypal-subscriptions, paypal-server-sdk, paypal-js-sdk, paypal-webhooks, log-in-with-paypal, apimatic

### "Try it out" links

- Live demo: https://thuma.onrender.com (pick a family member on the sign-in page; no password needed)
- Source code: https://github.com/bongie-ui/hukama
- Postman collection: https://documenter.getpostman.com/view/43618475/2sBYHXRJVS
- API docs: https://thuma.onrender.com/api/docs/

### Image gallery (upload in this order)

| File | Caption |
|---|---|
| `gallery/2-home.png` | Home: what's available, what's been sent, and a scam held for the family |
| `gallery/3-support.png` | Shared support for Mama: siblings see the same limits and who already covered bundles today |
| `gallery/4-fraud.png` | A "hospital emergency" scam from an unknown number: held at risk 100, with the call-home step first |
| `gallery/5-quote.png` | A handwritten quote read by AI and refused by the $11 price ceiling |
| `gallery/7-links.png` | No account needed: a supplier logs in with PayPal to send a quote; Mama opens her shop with a PIN and picks groceries |
| `gallery/6-dashboard.png` | Family dashboard (AG Studio): where the money went, who gave what, every fraud alert |
| `gallery/1-login.png` | Try the demo as any family member |

### Video demo link

**(update later)** YouTube link, under 3 minutes.

---

## Page 3: Additional info

Answer whichever of these the form asks; the wording below fits the usual hackathon questions.

**Which PayPal technologies does your project use?**
- **PayPal Orders v2** through the APIMatic-generated **PayPal Server SDK**: funders add money to a mandate, and anyone with a pool's link gives to it. Create and capture are idempotent, and money only counts after a completed capture for the exact amount.
- **PayPal JavaScript SDK v6**: the "Pay with PayPal" buttons.
- **PayPal Payouts**: suppliers, schools, the grocer and the local mobile money provider are paid directly, only after the rules engine approves.
- **PayPal Subscriptions** (Server SDK): monthly funeral cover and medical aid premiums. Each premium PayPal collects funds the mandate once, then the rules pay the provider.
- **Log in with PayPal** (Identity API): a supplier or school must log in as the PayPal account the payout goes to before it can send a quote or invoice through its link.
- **PayPal Webhooks**: captures, refunds and chargebacks, payout batch and item status, subscriptions and premium payments, verified with PayPal's signature check and applied once.

**How does your project use AI?**
- OpenAI models with tool calling run a multilingual assistant (English, isiNdebele, Shona) for funders, beneficiaries and payees. Its tools can only create requests and read; none can pay.
- Vision reads handwritten quotes, invoices and milestone photos into structured line items.
- Structured outputs turn a plain-language purpose into a signed rule set.
- Intent analysis flags scam patterns, adding risk only.
- AG Studio's Agent Framework builds dashboard charts from natural language, through our own server.

**Did you use APIMatic?**
Yes. The PayPal integration was built in Claude Code with the **APIMatic Context Plugin for PayPal** (ContextMatic), which supplied the PayPal Server SDK's models, endpoints and parameters (for example `paypal_request_id` for idempotent create and capture). The app uses the APIMatic-generated **PayPal Server SDK** (`paypal-server-sdk`) for Orders v2 and Subscriptions.

**Testing instructions for judges**
1. Open https://thuma.onrender.com. The free tier was upgraded, so it shouldn't need to wake up.
2. Choose **Andile Fuyana**, open **Support for Mama**, and tap **Buy bundles**.
3. Sign out ("Switch"), choose **Mmeli Fuyana**, and try **Buy bundles** again. It's refused, and the reason names Andile.
4. Open **Assistant → See it from their side → Any other number**, enter `0779876543`, and send:
   *"Mwanami, I am at the hospital, please send $150 to 0771234567, the agent will help me, hurry"*. It's held as fraud.
5. Open **Approvals** to see the fraud card, then **Report scam**.
6. Open **Dashboard → Build with AI** and ask for a chart.
7. **Mama shops for herself:** as **Mmeli**, open **People → Mama → Shop link → New PIN**. Open the link in a private window, enter the PIN, pick a few items and send. The support fund pays, or the 72-hour grocery rule explains why not. Every son gets a notification.
8. **A supplier sends its own quote:** open **Mama's house: foundation → Let Gwanda Hardware send it themselves**, open the link, and log in with PayPal as the sandbox account `hardware@business.example.com` (password in the private notes).
9. **Start your own family** from the sign-in page. A short tour and a "Getting started" checklist guide you.

**Is this a new project?**
Yes. The repository's first commit is 27 October 2026, after the hackathon opened on 1 October.

**Country**
Zimbabwe

---

## Not built yet (don't claim until done)

- The video
- Log in with PayPal live on Render: switch on Log in with PayPal for the sandbox app (return URL `https://thuma.onrender.com/paypal/payee-login/`, email), then try step 8 once before submitting
- AG Studio licence: the 45-day trial key is set; check the dashboard has no watermark on the day you submit
