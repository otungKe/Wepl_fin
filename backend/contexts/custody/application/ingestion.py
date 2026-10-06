"""Use case: take in statement lines from a custodian and account for each."""
from django.db import transaction

from contexts.audit.public import operation, record
from contexts.communities.public import CommunityError, fund_view, funds, group_view, hold_open_fund, members
from contexts.governance.public import execute_mandate, find_by_reference, issued_for_amount, mandate
from contexts.ledger.public import cash_by_fund
from contexts.notifications.public import notify

from ..contract import CustodyError, IngestResult
from ..domain import accounting
from ..domain.attribution import MemberFacts, attribute
from ..domain.matching import match_outflow, quoted_references
from ..domain.resolution import Outcome
from ..domain.routing import fund_for, quoted_codes, split_across_funds, unclear_code
from ..domain.sharing import Event
from ..domain.statement import BankLine, LineKind
from ..infrastructure.models import Alert, ExternalAccount, PayerMapping, StatementLine
from . import bookkeeping as bk


def ingest(ea_id: int, bank_lines) -> IngestResult:
    """Each line is taken in, in the custodian's order, in its own transaction
    with the account row locked, so ingestion can run concurrently and be
    repeated safely. A line seen before is ignored; a line resent with
    different details raises a conflict alert and is not posted."""
    result = IngestResult()
    with operation("custody.ingest", actor="system"):
        for bl in sorted(bank_lines, key=lambda l: l.sequence):
            with transaction.atomic():  # one custodian fact: store, account for, resolve
                ea = ExternalAccount.objects.select_for_update().get(pk=ea_id)
                existing = StatementLine.objects.filter(external_account=ea, external_id=bl.external_id).first()
                if existing is not None:
                    if bl.same_fact_as(existing.kind, existing.amount, existing.sequence):
                        result.duplicates += 1
                    else:
                        _conflict(ea, existing, bl)
                        result.conflicts += 1
                    continue
                if ea.closed_at is not None:  # the database refuses it too (custody 0007)
                    raise CustodyError(f"{ea.institution} {ea.account_number} was closed on {ea.closed_at:%d %b %Y}, "
                                       f"but the custodian reports a new transaction {bl.external_id}.")
                line = StatementLine.objects.create(
                    external_account=ea, external_id=bl.external_id, sequence=bl.sequence, posted_at=bl.posted_at,
                    kind=LineKind(bl.kind), amount=bl.amount, narration=bl.narration[:255],
                    reference=bl.reference[:64], counterparty_name=bl.counterparty_name[:120],
                    counterparty_msisdn=bl.counterparty_msisdn[:16], running_balance=bl.running_balance,
                    metadata=bl.metadata)
                account_for(ea, line)
                result.new += 1
    return result


def _conflict(ea: ExternalAccount, existing: StatementLine, bl: BankLine) -> None:
    alert, created = Alert.objects.get_or_create(
        kind=Alert.Kind.STATEMENT_CONFLICT, line=existing,
        defaults={"group_id": ea.group_id,
                  "message": (f"Custodian resent {bl.external_id} with different details ({bl.kind} {bl.amount} "
                              f"vs {existing.kind} {existing.amount}).")[:255]})
    if created:
        record("system", "custody.statement_conflict", target_type="statement_line", target_id=existing.pk,
               group_id=ea.group_id, data={"resent_amount": str(bl.amount), "resent_kind": str(bl.kind)})
        notify("ops.statement_conflict", {"line_id": existing.pk, "alert_id": alert.pk},
               dedupe_key=f"ops.statement_conflict:{alert.pk}")


def account_for(ea: ExternalAccount, line: StatementLine) -> None:
    """Decide and post the accounting for a new line. Idempotent: the journal
    key is derived from the line, so a retry after a crash posts nothing new."""
    if bk.latest_outcome(line) is not None:
        return
    handler = {LineKind.DEPOSIT: _deposit, LineKind.INTEREST: _interest, LineKind.CHARGE: _charge,
               LineKind.WITHDRAWAL: _withdrawal}[LineKind(line.kind)]
    handler(ea, line)


def fund_codes(group_id: int) -> dict[str, int]:
    return {f.code: f.id for f in funds(group_id) if f.code}


def _route(ea, line) -> tuple[int, str, dict[str, int]]:
    """The fund the pay-in is for (ADR-0023), locked against closing until
    this line commits (ADR-0026): a fund that closed since its code was read
    is routed again, as if its code were unknown. The default fund cannot
    close while the account is open."""
    codes = fund_codes(ea.group_id)
    fund_id, reference = fund_for(line.reference, codes, ea.fund_id)
    if fund_id != ea.fund_id:
        try:
            hold_open_fund(fund_id)
        except CommunityError:
            codes = fund_codes(ea.group_id)
            fund_id, reference = fund_for(line.reference, codes, ea.fund_id)
    return fund_id, reference, codes


def _deposit(ea, line):
    fund_id, reference, codes = _route(ea, line)
    group_members = members(ea.group_id, active_only=False)  # ended spells too: their codes stay theirs
    remembered = dict(PayerMapping.objects.filter(group_id=ea.group_id).values_list("msisdn", "membership_id"))
    member_id = attribute(reference=reference, narration=line.narration, payer_msisdn=line.counterparty_msisdn,
                          members=[MemberFacts(m.id, m.code, m.msisdn, m.is_active) for m in group_members],
                          remembered_payers=remembered)
    draft = accounting.receipt(bk.book(ea, fund_id), key=f"line:{line.pk}:receipt", line_id=line.pk, amount=bk.amount(line),
                               member_id=member_id, fine=bk.takes_fines(ea, fund_id))
    quoted, why = quoted_codes(line.reference, codes), unclear_code(line.reference, codes)
    via = f"Fund code {quoted[0]}" if quoted and not why else ""  # which code routed it, kept on the line
    if member_id:
        bk.post_and_resolve(line, draft, Outcome.ATTRIBUTED, membership_id=member_id, note=via)
        member = next(m for m in group_members if m.id == member_id)
        notify("contribution.received", {"msisdn": member.msisdn, "group_id": ea.group_id,
                                         "amount": str(line.amount), "external_id": line.external_id},
               dedupe_key=f"contribution.received:{line.pk}")
    else:
        bk.post_and_resolve(line, draft, Outcome.UNATTRIBUTED, note="; ".join(filter(None, ["Payer not recognised", via])))
        # For whoever the group granted correct_records, not a title (ADR-0011).
        notify("payer.unidentified", {"group_id": ea.group_id, "line_id": line.pk, "amount": str(line.amount),
                                      "payer": line.counterparty_name, "msisdn": line.counterparty_msisdn},
               dedupe_key=f"payer.unidentified:{line.pk}")
    if why:
        _unclear_code(ea, line, why)


def _unclear_code(ea, line, why: str) -> None:
    """The pay-in went to the default fund because its reference named no one
    fund (ADR-0026). A corrector moves it (``move_pay_in``) or confirms it
    stays (``keep_pay_in``); either closes the alert."""
    alert = Alert.objects.create(
        group_id=ea.group_id, kind=Alert.Kind.FUND_CODE_UNCLEAR, line=line,
        message=(f"{line.amount} received on {line.posted_at:%d %b %Y} went to {fund_view(ea.fund_id).name}: "
                 f"{why}.")[:255])
    record("system", "custody.fund_code_unclear", target_type="statement_line", target_id=line.pk,
           group_id=ea.group_id, data={"reference": line.reference, "reason": why, "alert_id": alert.pk})


def _interest(ea, line):
    _returns(ea, line, accounting.interest, "interest", bk.rules(ea).interest, Outcome.INTEREST)


def _charge(ea, line):
    _returns(ea, line, accounting.charge, "charge", bk.rules(ea).bank_charges, Outcome.CHARGE)


def _returns(ea, line, decide, name, rule, outcome):
    """Interest or a charge on the account: split among the funds held there
    as the group chose (ADR-0023), then inside each fund as its rule says.
    One entry and one resolution per fund, all in this line's transaction."""
    parts = split_across_funds(bk.amount(line), cash_by_fund(ea.pk, ea.currency), bk.rules(ea).account_split,
                               ea.fund_id)
    for fund_id, part in sorted(parts.items()):
        ids, balances = bk.sharing_facts(ea, fund_id, at=line.posted_at, event=Event.RETURNS)
        key = f"line:{line.pk}:{name}" if fund_id == ea.fund_id else f"line:{line.pk}:{name}:fund:{fund_id}"
        draft = decide(bk.book(ea, fund_id), key=key, line_id=line.pk, amount=part, rule=rule, member_ids=ids,
                       balances=balances)
        bk.post_and_resolve(line, draft, outcome)


def _withdrawal(ea, line):
    amount = bk.amount(line)
    quoted = quoted_references(line.narration, line.reference)
    match = match_outflow(amount=amount, payee_msisdn=line.counterparty_msisdn, quoted=quoted,
                          referenced=find_by_reference(ea.group_id, quoted) if quoted else None,
                          candidates=[] if quoted else issued_for_amount(ea.group_id, amount))
    if match.mandate_id and execute_mandate(match.mandate_id, line_id=line.pk, when=line.posted_at):
        m = mandate(match.mandate_id)
        # the mandate names the fund it spends (ADR-0023)
        ids, balances = bk.sharing_facts(ea, m.fund_id, at=line.posted_at, event=Event.PAYOUT, approved_at=m.issued_at)
        draft = accounting.authorised_payout(bk.book(ea, m.fund_id), key=f"line:{line.pk}:payout", line_id=line.pk, amount=amount,
                                             allocation=m.allocation, charged_member_id=m.charged_member_id,
                                             member_ids=ids, balances=balances, reference=m.reference)
        bk.post_and_resolve(line, draft, Outcome.MATCHED, mandate_id=m.id, note=match.reason)
        return
    reason = match.reason if not match.mandate_id else "The mandate was already used."
    # held in the default fund until someone explains it; which fund it spent is unknown
    draft = accounting.unexplained_payout(bk.book(ea), key=f"line:{line.pk}:payout", line_id=line.pk, amount=amount)
    bk.post_and_resolve(line, draft, Outcome.UNMATCHED, note=reason)
    alert = Alert.objects.create(
        group_id=ea.group_id, kind=Alert.Kind.UNMATCHED_OUTFLOW, line=line,
        message=(f"{amount} left the account on {line.posted_at:%d %b %Y} with no approved mandate. {reason}")[:255])
    record("system", "custody.unmatched_outflow", target_type="statement_line", target_id=line.pk, group_id=ea.group_id,
           data={"amount": str(line.amount), "reason": reason, "alert_id": alert.pk})
    group_name = group_view(ea.group_id).name
    for m in members(ea.group_id):
        notify("alert.unmatched_outflow", {"msisdn": m.msisdn, "group": group_name, "amount": str(line.amount),
                                           "date": line.posted_at.date().isoformat(),
                                           "counterparty": line.counterparty_name, "alert_id": alert.pk},
               dedupe_key=f"alert.unmatched_outflow:{alert.pk}:{m.id}")
