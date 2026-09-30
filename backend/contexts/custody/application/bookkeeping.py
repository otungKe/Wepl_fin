"""Gathers the facts an accounting decision needs, and records its outcome."""
from contexts.communities.public import members
from contexts.governance.public import ConstitutionRules, current_rules
from contexts.ledger.public import JournalDraft, member_balances, post_journal
from contexts.shared_kernel.money import Money

from ..contract import CustodyError
from ..domain.accounting import FundBook
from ..domain.resolution import Outcome
from ..infrastructure.models import ExternalAccount, LineResolution, StatementLine


def book(ea: ExternalAccount) -> FundBook:
    return FundBook(group_id=ea.group_id, fund_id=ea.fund_id, external_account_id=ea.pk, currency=ea.currency)


def rules(ea: ExternalAccount) -> ConstitutionRules:
    r = current_rules(ea.group_id)
    if r is None:
        raise CustodyError("The group has no constitution yet.")
    return r


def sharing_facts(ea: ExternalAccount) -> tuple[list[int], dict[int, Money]]:
    """Active member ids and their balances, for anything shared pro rata."""
    return [m.id for m in members(ea.group_id)], member_balances(ea.fund_id, ea.currency)


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
