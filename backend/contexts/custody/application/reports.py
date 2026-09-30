"""Read-only projections for members, the group and the bank. Never a source of truth."""
from contexts.communities.public import group_view, members, membership
from contexts.ledger.public import fund_position, member_balances, member_movements
from contexts.shared_kernel.money import Money

from ..infrastructure.models import Alert, ExternalAccount, LineResolution, StatementLine
from .reconciliation import latest_reconciliation


def member_statement(membership_id: int, fund_id: int) -> dict:
    m = membership(membership_id)
    lines = member_movements(fund_id, m.id)
    return {"member": m.name, "code": m.code, "lines": lines,
            "balance": lines[-1]["balance"] if lines else Money.zero().amount}


def group_summary(ea_id: int) -> dict:
    ea = ExternalAccount.objects.get(pk=ea_id)
    pos = fund_position(ea.fund_id, ea.currency)
    held = member_balances(ea.fund_id, ea.currency)
    return {
        "group": group_view(ea.group_id).name, "account": f"{ea.institution} {ea.account_number}",
        "position": pos,
        "members": [{"code": m.code, "name": m.name, "status": m.status, "balance": held.get(m.id, Money.zero(ea.currency)).amount}
                    for m in members(ea.group_id, active_only=False)],
        "open_alerts": list(Alert.objects.filter(group_id=ea.group_id, resolved_at__isnull=True).order_by("id")
                            .values("kind", "message")),
        "last_reconciliation": latest_reconciliation(ea.pk),
    }


def open_alerts(group_id: int, kind: str | None = None) -> list[dict]:
    qs = Alert.objects.filter(group_id=group_id, resolved_at__isnull=True)
    if kind:
        qs = qs.filter(kind=kind)
    return list(qs.order_by("id").values("id", "kind", "line_id", "message"))


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
