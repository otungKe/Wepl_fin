"""Read-only projections for members, the group and the bank. Never a source of truth."""
from contexts.communities.public import fund_view, group_view, members, membership
from contexts.ledger.public import entry_funds, fund_position, member_balances, member_movements
from contexts.shared_kernel.money import Money

from ..domain.resolution import Outcome
from ..infrastructure.models import Alert, ExternalAccount, LineResolution, StatementLine
from .reconciliation import account_funds, account_position, latest_reconciliation


def member_statement(membership_id: int, fund_id: int) -> dict:
    m = membership(membership_id)
    lines = member_movements(fund_id, m.id)
    return {"member": m.name, "code": m.code, "lines": lines,
            "balance": lines[-1]["balance"] if lines else Money.zero().amount}


def group_summary(ea_id: int) -> dict:
    """The account and every fund held at it (ADR-0023). A member's
    ``balance`` is what they hold across those funds; ``funds`` has each."""
    ea = ExternalAccount.objects.get(pk=ea_id)
    cur, zero = ea.currency, Money.zero(ea.currency)
    by_fund = {f: member_balances(f, cur) for f in account_funds(ea)}
    held = lambda m: sum((b.get(m, zero) for b in by_fund.values()), zero).amount
    return {
        "group": group_view(ea.group_id).name, "account": f"{ea.institution} {ea.account_number}",
        "position": account_position(ea),
        "funds": [{"fund": fund_view(f).name, "code": fund_view(f).code, "default": f == ea.fund_id,
                   "position": fund_position(f, cur)} for f in by_fund],
        "members": [{"code": m.code, "name": m.name, "status": m.status, "balance": held(m.id)}
                    for m in members(ea.group_id, active_only=False)],
        "open_alerts": list(Alert.objects.filter(group_id=ea.group_id, resolved_at__isnull=True).order_by("id")
                            .values("kind", "message")),
        "last_reconciliation": latest_reconciliation(ea.pk),
    }


def open_alerts(group_id: int, kind: str | None = None) -> list[dict]:
    qs = Alert.objects.filter(group_id=group_id, resolved_at__isnull=True)
    if kind:
        qs = qs.filter(kind=kind)
    return list(qs.order_by("id").values("id", "kind", "line_id", "message", "created_at"))


def line_trail(line_id: int) -> dict:
    """From one custodian transaction to every accounting decision about it."""
    line = StatementLine.objects.get(pk=line_id)
    return {"external_id": line.external_id, "kind": line.kind, "amount": line.amount, "posted_at": line.posted_at,
            "resolutions": list(LineResolution.objects.filter(line=line).order_by("id").values(
                "outcome", "membership_id", "mandate_id", "journal_entry_id", "actor", "note", "created_at"))}


def statement_lines(ea_id: int) -> list[dict]:
    """The custodian's statement as received, with how each line stands now."""
    out = []
    for line in StatementLine.objects.filter(external_account_id=ea_id).order_by("sequence"):
        last = line.resolutions.order_by("-id").first()
        out.append({"id": line.pk, "external_id": line.external_id, "sequence": line.sequence, "kind": line.kind,
                    "amount": line.amount, "narration": line.narration, "reference": line.reference,
                    "counterparty_name": line.counterparty_name, "counterparty_msisdn": line.counterparty_msisdn,
                    "outcome": last.outcome if last else None})
    return out


def member_pay_ins(fund_id: int, membership_id: int) -> list[tuple]:
    """Pay-ins credited to a member in a fund, as (the bank's date, amount),
    oldest first; a payment credited later by a corrector keeps its bank
    date. Opening balances are not pay-ins (ADR-0022)."""
    found = list(LineResolution.objects.filter(outcome=Outcome.ATTRIBUTED, membership_id=membership_id)
                 .select_related("line__external_account").order_by("line__posted_at", "id"))
    funds = entry_funds(r.journal_entry_id for r in found)
    return [(r.line.posted_at, Money(r.line.amount, r.line.external_account.currency))
            for r in found if funds.get(r.journal_entry_id) == fund_id]
