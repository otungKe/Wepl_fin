"""Read-only views of a group's money, for members, officials and the bank."""
from decimal import Decimal

from governance.models import Membership
from ledger import services as ledger
from ledger.models import Account, JournalLine

from .models import Alert, ExternalAccount

P = Account.Purpose


def member_statement(membership: Membership, fund_id: int) -> dict:
    """Every movement on one member's interest in a fund, with a running balance."""
    rows = (JournalLine.objects
            .filter(account__fund_id=fund_id, account__purpose=P.MEMBER_INTEREST,
                    account__member_id=membership.pk)
            .select_related("entry").order_by("entry_id", "id"))
    running, lines = Decimal("0.00"), []
    for r in rows:
        running += r.amount if r.side == Account.Side.CREDIT else -r.amount
        lines.append({"date": r.entry.created_at, "kind": r.entry.kind, "memo": r.entry.memo,
                      "in": r.amount if r.side == Account.Side.CREDIT else None,
                      "out": r.amount if r.side == Account.Side.DEBIT else None,
                      "balance": running})
    return {"member": membership.person.display_name, "code": membership.member_code,
            "lines": lines, "balance": running}


def group_summary(ea: ExternalAccount) -> dict:
    position = ledger.fund_position(ea.fund_id)
    held = ledger.balances(ea.fund_id, P.MEMBER_INTEREST)
    members = Membership.objects.filter(group_id=ea.group_id).select_related("person").order_by("member_code")
    last_run = ea.reconciliations.order_by("-id").first()
    return {
        "group": ea.group.name,
        "account": str(ea),
        "cash": position[P.CUSTODY_CASH],
        "member_interests": position[P.MEMBER_INTEREST],
        "unattributed": position[P.UNATTRIBUTED_IN],
        "unexplained_out": position[P.UNEXPLAINED_OUT],
        "retained": position[P.RETAINED],
        "members": [{"code": m.member_code, "name": m.person.display_name,
                     "balance": held.get(m.pk, Decimal("0.00"))} for m in members],
        "open_alerts": list(Alert.objects.filter(group_id=ea.group_id, resolved_at__isnull=True)
                            .order_by("id").values("kind", "message")),
        "last_reconciliation": last_run,
    }
