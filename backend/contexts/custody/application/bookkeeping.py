"""Gathers the facts an accounting decision needs, and records its outcome."""
from contexts.communities.public import CommunityError, MembershipView, members, membership
from contexts.governance.public import ConstitutionRules, LeaverRuleVersion, current_rules, rules_in_force
from contexts.ledger.public import JournalDraft, entry_fund, member_balances, post_journal
from contexts.shared_kernel.money import Money

from ..contract import CustodyError
from ..domain.accounting import FundBook
from ..domain.resolution import Outcome
from ..domain.sharing import Event, Spell, sharers
from ..infrastructure.models import ExternalAccount, LineResolution, StatementLine


def book(ea: ExternalAccount, fund_id: int | None = None) -> FundBook:
    """One fund's books at this account; the group's default fund unless
    another is named (ADR-0023)."""
    return FundBook(group_id=ea.group_id, fund_id=fund_id or ea.fund_id, external_account_id=ea.pk,
                    currency=ea.currency)


def line_fund(line: StatementLine) -> int:
    """The fund whose books the line's latest accounting is in."""
    return entry_fund(line.resolutions.order_by("-id").values_list("journal_entry_id", flat=True)[0])


def rules(ea: ExternalAccount) -> ConstitutionRules:
    r = current_rules(ea.group_id)
    if r is None:
        raise CustodyError("The group has no constitution yet.")
    return r


def sharing_facts(ea: ExternalAccount, fund_id: int, *, at, event: Event,
                  approved_at=None) -> tuple[list[int], dict[int, Money]]:
    """Who shares an event dated ``at`` in a fund, and their balances in it
    (ADR-0014; the rule itself is ``domain.sharing``). Each leaver is judged
    by the group's own choices: the version in force when they left, or the
    one in force at the event, as the group's ``leaver_rule_version`` says."""
    balances = member_balances(fund_id, ea.currency)
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


def takes_fines(ea: ExternalAccount, fund_id: int) -> bool:
    """Whether the group named this fund for fines to be paid into (ADR-0022)."""
    r = current_rules(ea.group_id)
    return r is not None and fund_id in r.fines_funds


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
