"""Gathers the facts an accounting decision needs, and records its outcome."""
from contexts.communities.public import CommunityError, MembershipView, members, membership
from contexts.governance.public import ConstitutionRules, LeaverRuleVersion, current_rules, rules_in_force
from contexts.ledger.public import JournalDraft, member_balances, post_journal
from contexts.shared_kernel.money import Money

from ..contract import CustodyError
from ..domain.accounting import FundBook
from ..domain.resolution import Outcome
from ..domain.sharing import Event, Spell, sharers
from ..infrastructure.models import ExternalAccount, LineResolution, StatementLine


def book(ea: ExternalAccount) -> FundBook:
    return FundBook(group_id=ea.group_id, fund_id=ea.fund_id, external_account_id=ea.pk, currency=ea.currency)


def rules(ea: ExternalAccount) -> ConstitutionRules:
    r = current_rules(ea.group_id)
    if r is None:
        raise CustodyError("The group has no constitution yet.")
    return r


def sharing_facts(ea: ExternalAccount, *, at, event: Event, approved_at=None) -> tuple[list[int], dict[int, Money]]:
    """Who shares an event dated ``at``, and their balances (ADR-0014; the
    rule itself is ``domain.sharing``). Each leaver is judged by the group's
    own choices: the version in force when they left, or the one in force at
    the event, as the group's ``leaver_rule_version`` says."""
    balances = member_balances(ea.fund_id, ea.currency)
    now = rules_in_force(ea.group_id, at)
    spells = []
    for m in members(ea.group_id, active_only=False):
        r = _leaver_rules(ea.group_id, m.left_at, now[1] if now else None)
        spells.append(Spell(m.id, m.joined_at, m.left_at, r.leaver_treatment if r else None,
                            r.leaver_payout_share if r else None))
    return sharers(spells, at=at, event=event, balances=balances, approved_at=approved_at), balances


def _leaver_rules(group_id: int, left_at, at_event: ConstitutionRules | None) -> ConstitutionRules | None:
    if left_at is None:
        return None
    if at_event is not None and at_event.leaver_version is LeaverRuleVersion.CURRENT:
        return at_event
    found = rules_in_force(group_id, left_at)
    return found[1] if found else None


def amount(line: StatementLine) -> Money:
    return Money(line.amount, line.external_account.currency)


def latest_outcome(line: StatementLine) -> Outcome | None:
    last = line.resolutions.order_by("-id").first()
    return Outcome(last.outcome) if last else None


def post_and_resolve(line: StatementLine, draft: JournalDraft, outcome: Outcome, *, membership_id=None,
                     mandate_id=None, note: str = "", actor: str = "system") -> LineResolution:
    entry_id = post_journal(draft)
    return LineResolution.objects.create(line=line, outcome=outcome, journal_entry_id=entry_id,
                                         membership_id=membership_id, mandate_id=mandate_id, note=note[:255],
                                         actor=actor)


def member_of(group_id: int, membership_id: int) -> MembershipView:
    """The member, if they are in this group. An unknown id and another
    tenant's id (invisible under row-level security) read the same."""
    try:
        m = membership(membership_id)
    except CommunityError:
        m = None
    if m is None or m.group_id != group_id:
        raise CustodyError("That member is not in this group.")
    return m
