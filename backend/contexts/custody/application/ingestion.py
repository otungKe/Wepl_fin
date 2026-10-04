"""Use case: take in statement lines from a custodian and account for each."""
from django.db import transaction

from contexts.audit.public import operation, record
from contexts.communities.public import group_view, members
from contexts.governance.public import execute_mandate, find_by_reference, issued_for_amount, mandate
from contexts.notifications.public import notify

from ..contract import CustodyError, IngestResult
from ..domain import accounting
from ..domain.attribution import MemberFacts, attribute
from ..domain.matching import match_outflow, quoted_references
from ..domain.resolution import Outcome
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


def _deposit(ea, line):
    group_members = members(ea.group_id, active_only=False)  # ended spells too: their codes stay theirs
    remembered = dict(PayerMapping.objects.filter(group_id=ea.group_id).values_list("msisdn", "membership_id"))
    member_id = attribute(reference=line.reference, narration=line.narration, payer_msisdn=line.counterparty_msisdn,
                          members=[MemberFacts(m.id, m.code, m.msisdn, m.is_active) for m in group_members],
                          remembered_payers=remembered)
    draft = accounting.receipt(bk.book(ea), key=f"line:{line.pk}:receipt", line_id=line.pk, amount=bk.amount(line),
                               member_id=member_id)
    if member_id:
        bk.post_and_resolve(line, draft, Outcome.ATTRIBUTED, membership_id=member_id)
        member = next(m for m in group_members if m.id == member_id)
        notify("contribution.received", {"msisdn": member.msisdn, "group_id": ea.group_id,
                                         "amount": str(line.amount), "external_id": line.external_id},
               dedupe_key=f"contribution.received:{line.pk}")
    else:
        bk.post_and_resolve(line, draft, Outcome.UNATTRIBUTED, note="Payer not recognised")
        # For whoever the group granted correct_records, not a title (ADR-0011).
        notify("payer.unidentified", {"group_id": ea.group_id, "line_id": line.pk, "amount": str(line.amount),
                                      "payer": line.counterparty_name, "msisdn": line.counterparty_msisdn},
               dedupe_key=f"payer.unidentified:{line.pk}")


def _interest(ea, line):
    ids, balances = bk.sharing_facts(ea, at=line.posted_at, event=Event.RETURNS)
    draft = accounting.interest(bk.book(ea), key=f"line:{line.pk}:interest", line_id=line.pk, amount=bk.amount(line),
                                rule=bk.rules(ea).interest, member_ids=ids, balances=balances)
    bk.post_and_resolve(line, draft, Outcome.INTEREST)


def _charge(ea, line):
    ids, balances = bk.sharing_facts(ea, at=line.posted_at, event=Event.RETURNS)
    draft = accounting.charge(bk.book(ea), key=f"line:{line.pk}:charge", line_id=line.pk, amount=bk.amount(line),
                              rule=bk.rules(ea).bank_charges, member_ids=ids, balances=balances)
    bk.post_and_resolve(line, draft, Outcome.CHARGE)


def _withdrawal(ea, line):
    amount = bk.amount(line)
    quoted = quoted_references(line.narration, line.reference)
    match = match_outflow(amount=amount, payee_msisdn=line.counterparty_msisdn, quoted=quoted,
                          referenced=find_by_reference(ea.fund_id, quoted) if quoted else None,
                          candidates=[] if quoted else issued_for_amount(ea.fund_id, amount))
    if match.mandate_id and execute_mandate(match.mandate_id, line_id=line.pk, when=line.posted_at):
        m = mandate(match.mandate_id)
        ids, balances = bk.sharing_facts(ea, at=line.posted_at, event=Event.PAYOUT, approved_at=m.issued_at)
        draft = accounting.authorised_payout(bk.book(ea), key=f"line:{line.pk}:payout", line_id=line.pk, amount=amount,
                                             allocation=m.allocation, charged_member_id=m.charged_member_id,
                                             member_ids=ids, balances=balances, reference=m.reference)
        bk.post_and_resolve(line, draft, Outcome.MATCHED, mandate_id=m.id, note=match.reason)
        return
    reason = match.reason if not match.mandate_id else "The mandate was already used."
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
