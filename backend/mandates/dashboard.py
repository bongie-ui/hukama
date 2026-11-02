"""Family-wide numbers for the dashboard: flat tables for AG Studio and a summary for everyone else."""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from agent.policy import person
from payments.models import RailTransaction

from . import services
from .models import Funding, LedgerEntry, Mandate, Request
from .serializers import display_name
from .templates import TEMPLATES

PAID = (Request.PAID,)
FRAUD = (Request.HELD_FRAUD, Request.CONFIRMED_FRAUD)
OUTCOME = {
    Request.PAID: "Paid", Request.APPROVED: "Paying", Request.REFUSED: "Refused", Request.ESCALATED: "Needs approval",
    Request.HELD_FRAUD: "Held: possible fraud", Request.CONFIRMED_FRAUD: "Fraud reported", Request.FAILED: "Failed",
}
EVENT = dict(LedgerEntry.EVENTS)
ACTORS = {"POLICY": "Policy engine", "SYSTEM": "Hukama", "PAYPAL": "PayPal",
          "SIMULATED_RAIL": "Local mobile money (simulated rail)"}


def _kind(mandate):
    label = TEMPLATES[mandate.type].label
    return label[label.find("(") + 1:-1] if "(" in label else label


def _money(value):
    return float(value or 0)


def tables(family):
    """Rows per table, keyed by table id. Dates are ISO strings; money is a float in the mandate currency."""
    mandates = list(Mandate.objects.filter(family=family).exclude(status=Mandate.CLOSED))
    names = {m.user_id: display_name(m.user) for m in family.memberships.select_related("user")}

    mandate_rows = []
    for m in mandates:
        funded, balance = services.captured_total(m), services.mandate_balance(m)
        mandate_rows.append({"mandate_id": str(m.id), "mandate": m.title, "kind": _kind(m), "type": m.type,
                             "status": m.get_status_display(), "funded": _money(funded),
                             "available": _money(balance), "spent": _money(funded - balance),
                             "funders": m.mandate_funders.count()})

    funding_rows = [{"funding_id": str(f.id), "mandate_id": str(f.mandate_id),
                     "funder": names.get(f.funder_id, "Local contributor"), "amount": _money(f.amount),
                     "rail": f.get_rail_display(), "date": f.created_at.date().isoformat()}
                    for f in Funding.objects.filter(mandate__in=mandates, status=Funding.CAPTURED)]

    request_rows = []
    for r in Request.objects.filter(mandate__in=mandates).select_related("requester_user", "risk_assessment"):
        risk = getattr(r, "risk_assessment", None)
        request_rows.append({
            "request_id": str(r.id), "mandate_id": str(r.mandate_id), "requested_by": person(r),
            "category": (r.product or "other").replace("_", " "), "amount": _money(r.amount),
            "paid": _money(r.amount) if r.status in PAID else 0.0, "outcome": OUTCOME.get(r.status, r.get_status_display()),
            "channel": r.get_channel_display(), "risk_level": risk.level.title() if risk else "Not checked",
            "risk_score": risk.score if risk else 0, "fraud_alert": 1 if r.status in FRAUD else 0,
            "date": r.created_at.date().isoformat(),
        })

    ledger_rows = [{"entry_id": str(e.id), "mandate_id": str(e.mandate_id), "event": EVENT.get(e.event, e.event),
                    "actor": names.get(int(e.actor), "Family member") if e.actor.isdigit() else ACTORS.get(e.actor, e.actor),
                    "amount": _money(e.amount), "date": e.created_at.date().isoformat(),
                    "time": timezone.localtime(e.created_at).strftime("%d %b %H:%M")}
                   for e in LedgerEntry.objects.filter(family=family).order_by("-created_at")[:500]]

    return {"mandates": mandate_rows, "fundings": funding_rows, "requests": request_rows, "ledger": ledger_rows}


def summary(family):
    """Headline numbers (also used by the Postman collection and anyone without the dashboard)."""
    mandates = Mandate.objects.filter(family=family).exclude(status=Mandate.CLOSED)
    funded = sum((services.captured_total(m) for m in mandates), Decimal("0"))
    available = sum((services.mandate_balance(m) for m in mandates), Decimal("0"))
    requests = Request.objects.filter(mandate__family=family)
    paid = requests.filter(status=Request.PAID).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    by_category = {row["product"] or "other": f"{row['t']:.2f}"
                   for row in requests.filter(status=Request.PAID).values("product").annotate(t=Sum("amount"))}
    return {
        "funded": f"{funded:.2f}", "available": f"{available:.2f}", "paid": f"{paid:.2f}",
        "mandates": mandates.count(),
        "requests": requests.count(),
        "refused": requests.filter(status=Request.REFUSED).count(),
        "fraud_held": requests.filter(status=Request.HELD_FRAUD).count(),
        "fraud_confirmed": requests.filter(status=Request.CONFIRMED_FRAUD).count(),
        "awaiting_approval": requests.filter(status=Request.ESCALATED).count(),
        "paid_by_category": by_category,
        "simulated_payouts": RailTransaction.objects.filter(request__mandate__family=family, simulated=True).count(),
    }
