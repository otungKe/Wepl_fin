"""Where members stand against their fund's contribution rule (ADR-0022).
Read-only: gathers the facts from the other contexts' public surfaces and
lets the domain work out the answer."""
from datetime import datetime, time

from django.utils import timezone

from contexts.communities.public import CommunityError, fund_view, members, membership
from contexts.custody.public import member_pay_ins
from contexts.governance.contract import LeaverArrears
from contexts.governance.public import rules_history, rules_in_force

from ..contract import ContributionsError, MemberStanding
from ..domain.schedule import periods
from ..domain.standing import standing


def member_standing(membership_id: int, fund_id: int, *, as_of=None) -> MemberStanding | None:
    """One member's standing in one fund on ``as_of`` (today by default), or
    None when the group has no contribution rule for the fund."""
    try:
        m, fund = membership(membership_id), fund_view(fund_id)
    except CommunityError as exc:
        raise ContributionsError(str(exc)) from None
    if m.group_id != fund.group_id:
        raise ContributionsError("That member is not in this fund's group.")
    as_of = as_of or timezone.localdate()
    found = rules_in_force(fund.group_id, timezone.make_aware(datetime.combine(as_of, time.max)))  # all of that day
    rule = found[1].contribution_rule(fund_id) if found else None
    if rule is None:
        return None
    versions = [(timezone.localdate(since), rules.contribution_rule(fund_id))
                for since, rules in rules_history(fund.group_id)]
    left_on = timezone.localdate(m.left_at) if m.left_at else None
    until = min(as_of, left_on) if left_on else as_of
    due = periods(versions, joined_on=timezone.localdate(m.joined_at), until=until, upcoming=left_on is None)
    paid = [(timezone.localdate(on), amount) for on, amount in member_pay_ins(fund_id, m.id)
            if timezone.localdate(on) <= as_of]
    s = standing(due, paid, as_of=until, order=rule.payment_order, extra=rule.extra_payments,
                 fine=rule.late_fine, write_off=left_on is not None and rule.leaver_arrears is LeaverArrears.WRITTEN_OFF)
    return MemberStanding(membership_id=m.id, code=m.code, name=m.name, active=m.is_active, fund_id=fund_id,
                          as_of=as_of, standing=s)


def fund_standing(fund_id: int, *, as_of=None) -> list[MemberStanding]:
    """Every member of the fund's group, current and former, oldest first.
    Empty when the group has no contribution rule for the fund."""
    group_id = fund_view(fund_id).group_id
    out = [member_standing(m.id, fund_id, as_of=as_of) for m in members(group_id, active_only=False)]
    return [s for s in out if s is not None]
