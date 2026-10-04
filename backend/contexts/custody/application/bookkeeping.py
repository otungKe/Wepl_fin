"""Gathers the facts an accounting decision needs, and records its outcome."""
from contexts.communities.public import CommunityError, MembershipView, members, membership
from contexts.governance.public import ConstitutionRules, current_rules, rules_in_force
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


def sharing_facts(ea: ExternalAccount, *, at, event: Event) -> tuple[list[int], dict[int, Money]]:
    """Who shares an event dated ``at``, and their balances (ADR-0014; the
    rule itself is ``domain.sharing``). A leaver is judged by the group's
    rule in force on the day they left."""
    balances = member_balances(ea.fund_id, ea.currency)
    spells = [Spell(m.id, m.joined_at, m.left_at, _leaver_rule(ea.group_id, m.left_at))
              for m in members(ea.group_id, active_only=False)]
    return sharers(spells, at=at, event=event, balances=balances), balances


def _leaver_rule(group_id: int, left_at):
    if left_at is None:
        return None
    found = rules_in_force(group_id, left_at)
    return found[1].leaver_treatment if found else None


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
