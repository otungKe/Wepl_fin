"""Turning custodian statement lines into ledger entries, and checking that
WEPL's books agree with the bank.

Every line is processed exactly once, in its own transaction, with the
external account locked, so ingestion is safe to run concurrently and to
repeat. Duplicate deliveries are ignored; conflicting ones raise an alert.
"""
import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from governance.models import Mandate, Membership, Proposal
from governance.services import claim_mandate, current_constitution
from ledger import services as ledger
from ledger.models import Account
from parties.models import normalize_msisdn
from platform_core import audit, outbox
from wepl.money import allocate, to_money

from .models import Alert, ExternalAccount, LineResolution, PayerMapping, ReconciliationRun, StatementLine

log = logging.getLogger(__name__)
P = Account.Purpose
D, C = Account.Side.DEBIT, Account.Side.CREDIT
Line = ledger.Line
Outcome = LineResolution.Outcome
MANDATE_REF = re.compile(r"\bWM[A-HJ-NP-Z2-9]{6}\b")


class ConnectivityError(ValidationError):
    pass


@dataclass
class IngestResult:
    new: int = 0
    duplicates: int = 0
    conflicts: int = 0


# ---------------------------------------------------------------- accounts

def _acct(ea: ExternalAccount, purpose: str, member_id: int | None = None) -> Account:
    return ledger.account(
        purpose, group_id=ea.group_id, fund_id=ea.fund_id, member_id=member_id,
        external_account_id=ea.pk if purpose == P.CUSTODY_CASH else None, currency=ea.currency)


def _post(ea: ExternalAccount, key: str, kind: str, cause, lines: list, memo: str = ""):
    return ledger.post(idempotency_key=key, group_id=ea.group_id, fund_id=ea.fund_id, kind=kind,
                       cause_type=type(cause).__name__, cause_id=cause.pk, lines=lines, memo=memo)


def _active_members(ea: ExternalAccount) -> list[Membership]:
    return list(Membership.objects.filter(group_id=ea.group_id, status=Membership.Status.ACTIVE)
                .select_related("person").order_by("pk"))


def _pro_rata(ea: ExternalAccount, amount: Decimal) -> dict[int, Decimal]:
    """Split by current member balances; equally if nobody has a positive balance."""
    members = _active_members(ea)
    if not members:
        raise ConnectivityError("The group has no active members to allocate to.")
    held = ledger.balances(ea.fund_id, P.MEMBER_INTEREST)
    weights = {m.pk: max(held.get(m.pk, Decimal(0)), Decimal(0)) for m in members}
    return allocate(amount, weights)


def _rules(ea: ExternalAccount) -> dict:
    constitution = current_constitution(ea.group)
    if constitution is None:
        raise ConnectivityError("The group has no constitution yet.")
    return constitution.rules


# ---------------------------------------------------------------- onboarding

@transaction.atomic
def record_opening_balances(ea: ExternalAccount, *, statement_balance, member_balances: dict,
                            actor: str) -> StatementLine | None:
    """Bring an existing account into WEPL. ``member_balances`` maps
    Membership -> amount, as signed off by the treasurer. Anything in the bank
    not accounted for by members is held as unattributed until resolved."""
    statement_balance = to_money(statement_balance)
    total = sum((to_money(v) for v in member_balances.values()), Decimal(0))
    if total > statement_balance:
        raise ConnectivityError("Member balances add up to more than the bank balance.")
    if ea.lines.exists():
        raise ConnectivityError("Opening balances must be recorded before any other statement line.")
    if statement_balance == 0:
        return None
    line = StatementLine.objects.create(
        external_account=ea, bank_txn_id="OPENING", sequence=0, posted_at=timezone.now(),
        kind=StatementLine.Kind.OPENING, amount=statement_balance, running_balance=statement_balance,
        narration="Opening balance brought forward")
    lines = [Line(_acct(ea, P.CUSTODY_CASH), D, statement_balance)]
    for membership, amount in member_balances.items():
        if to_money(amount) > 0:
            lines.append(Line(_acct(ea, P.MEMBER_INTEREST, membership.pk), C, to_money(amount)))
    if statement_balance - total > 0:
        lines.append(Line(_acct(ea, P.UNATTRIBUTED_IN), C, statement_balance - total))
    entry = _post(ea, f"line:{line.pk}:opening", "opening", line, lines, "Opening balances")
    LineResolution.objects.create(line=line, outcome=Outcome.OPENING, journal_entry_id=entry.pk, actor=actor)
    audit.record(actor, "account.opening_balances", ea,
                 {"statement_balance": str(statement_balance), "members_total": str(total)})
    return line


# ---------------------------------------------------------------- ingestion

def ingest(ea: ExternalAccount, bank_lines) -> IngestResult:
    result = IngestResult()
    for bl in sorted(bank_lines, key=lambda l: l.sequence):
        with transaction.atomic():
            ExternalAccount.objects.select_for_update().get(pk=ea.pk)
            existing = StatementLine.objects.filter(external_account=ea, bank_txn_id=bl.bank_txn_id).first()
            if existing:
                if (existing.amount, existing.kind, existing.sequence) != (to_money(bl.amount), bl.kind, bl.sequence):
                    _conflict(ea, existing, bl)
                    result.conflicts += 1
                else:
                    result.duplicates += 1
                continue
            line = StatementLine.objects.create(
                external_account=ea, bank_txn_id=bl.bank_txn_id, sequence=bl.sequence,
                posted_at=bl.posted_at, kind=bl.kind, amount=to_money(bl.amount),
                narration=bl.narration[:255], reference=bl.reference[:64],
                counterparty_name=bl.counterparty_name[:120], counterparty_msisdn=bl.counterparty_msisdn[:16],
                running_balance=bl.running_balance, raw=bl.raw)
            _process(ea, line)
            result.new += 1
    return result


def _conflict(ea, existing, bl):
    alert, created = Alert.objects.get_or_create(
        kind=Alert.Kind.STATEMENT_CONFLICT, line=existing,
        defaults={"group_id": ea.group_id,
                  "message": (f"Bank resent {bl.bank_txn_id} with different details "
                              f"({bl.kind} {bl.amount} vs {existing.kind} {existing.amount}).")[:255]})
    if created:
        outbox.emit("ops.statement_conflict", {"line_id": existing.pk, "alert_id": alert.pk})


def _process(ea: ExternalAccount, line: StatementLine) -> None:
    kind = line.kind
    if kind == StatementLine.Kind.DEPOSIT:
        _process_deposit(ea, line)
    elif kind == StatementLine.Kind.INTEREST:
        _process_interest(ea, line)
    elif kind == StatementLine.Kind.CHARGE:
        _process_charge(ea, line)
    elif kind == StatementLine.Kind.WITHDRAWAL:
        _process_withdrawal(ea, line)
    else:
        raise ConnectivityError(f"Unknown statement line kind {kind!r}.")


def _resolve(line, outcome, entry, *, membership=None, mandate=None, note="", actor="system"):
    return LineResolution.objects.create(line=line, outcome=outcome, journal_entry_id=entry.pk,
                                         membership=membership, mandate=mandate, note=note[:255], actor=actor)


# ---------------------------------------------------------------- inflows

def _attribute(ea: ExternalAccount, line: StatementLine) -> Membership | None:
    members = {m.member_code.upper(): m for m in _active_members(ea)}
    for token in re.findall(r"[A-Za-z0-9]+", f"{line.reference} {line.narration}"):
        if token.upper() in members:
            return members[token.upper()]
    try:
        msisdn = normalize_msisdn(line.counterparty_msisdn)
    except ValidationError:
        return None
    mapping = PayerMapping.objects.filter(group_id=ea.group_id, msisdn=msisdn,
                                          membership__status=Membership.Status.ACTIVE).first()
    if mapping:
        return mapping.membership
    return next((m for m in members.values() if m.person.msisdn == msisdn), None)


def _process_deposit(ea, line):
    member = _attribute(ea, line)
    cash = Line(_acct(ea, P.CUSTODY_CASH), D, line.amount)
    if member:
        entry = _post(ea, f"line:{line.pk}:deposit", "contribution", line,
                      [cash, Line(_acct(ea, P.MEMBER_INTEREST, member.pk), C, line.amount)])
        _resolve(line, Outcome.ATTRIBUTED, entry, membership=member)
        outbox.emit("contribution.received", {
            "msisdn": member.person.msisdn, "group": ea.group.name, "amount": str(line.amount),
            "bank_txn_id": line.bank_txn_id})
    else:
        entry = _post(ea, f"line:{line.pk}:deposit", "unattributed_receipt", line,
                      [cash, Line(_acct(ea, P.UNATTRIBUTED_IN), C, line.amount)])
        _resolve(line, Outcome.UNATTRIBUTED, entry, note="Payer not recognised")
        outbox.emit("treasurer.identify_payer", {
            "group": ea.group.name, "line_id": line.pk, "amount": str(line.amount),
            "payer": line.counterparty_name, "msisdn": line.counterparty_msisdn})


def _process_interest(ea, line):
    cash = Line(_acct(ea, P.CUSTODY_CASH), D, line.amount)
    if _rules(ea).get("interest") == "retained":
        credits = [Line(_acct(ea, P.RETAINED), C, line.amount)]
    else:
        credits = [Line(_acct(ea, P.MEMBER_INTEREST, mid), C, amt)
                   for mid, amt in _pro_rata(ea, line.amount).items()]
    entry = _post(ea, f"line:{line.pk}:interest", "interest", line, [cash, *credits])
    _resolve(line, Outcome.INTEREST, entry)


# ---------------------------------------------------------------- outflows

def _process_charge(ea, line):
    cash = Line(_acct(ea, P.CUSTODY_CASH), C, line.amount)
    if _rules(ea).get("bank_charges") == "retained":
        debits = [Line(_acct(ea, P.RETAINED), D, line.amount)]
    else:
        debits = [Line(_acct(ea, P.MEMBER_INTEREST, mid), D, amt)
                  for mid, amt in _pro_rata(ea, line.amount).items()]
    entry = _post(ea, f"line:{line.pk}:charge", "bank_charge", line, [*debits, cash])
    _resolve(line, Outcome.CHARGE, entry)


def _mandate_debits(ea, mandate: Mandate, amount: Decimal) -> list:
    if mandate.allocation == Proposal.Allocation.MEMBER:
        return [Line(_acct(ea, P.MEMBER_INTEREST, mandate.charged_member_id), D, amount)]
    return [Line(_acct(ea, P.MEMBER_INTEREST, mid), D, amt) for mid, amt in _pro_rata(ea, amount).items()]


def _find_mandate(ea, line) -> tuple[Mandate | None, str]:
    """Find the mandate that authorises an outflow. Returns (mandate, reason)."""
    refs = MANDATE_REF.findall(f"{line.narration} {line.reference}")
    if refs:
        mandate = Mandate.objects.filter(reference__in=refs, fund_id=ea.fund_id).first()
        if mandate is None:
            return None, f"Reference {refs[0]} is not a mandate of this fund."
        if mandate.status != Mandate.Status.ISSUED:
            return None, f"Mandate {mandate.reference} is {mandate.status}."
        if mandate.amount != line.amount:
            return None, f"Mandate {mandate.reference} is for {mandate.amount}, bank paid {line.amount}."
        return mandate, f"Matched by reference {mandate.reference}."
    # No reference quoted: accept only a single unambiguous candidate.
    candidates = list(Mandate.objects.filter(fund_id=ea.fund_id, status=Mandate.Status.ISSUED,
                                             amount=line.amount))
    if line.counterparty_msisdn:
        try:
            msisdn = normalize_msisdn(line.counterparty_msisdn)
            candidates = [m for m in candidates if _same_payee(m.payee_account, msisdn)]
        except ValidationError:
            pass
    if len(candidates) == 1:
        return candidates[0], "Matched by amount and payee (no reference quoted)."
    if len(candidates) > 1:
        return None, "Several mandates could match; the treasurer must quote the reference."
    return None, "No approved mandate for this payment."


def _same_payee(payee_account: str, msisdn: str) -> bool:
    try:
        return normalize_msisdn(payee_account) == msisdn
    except ValidationError:
        return False


def _process_withdrawal(ea, line):
    mandate, reason = _find_mandate(ea, line)
    cash = Line(_acct(ea, P.CUSTODY_CASH), C, line.amount)
    if mandate and claim_mandate(mandate.pk, line_id=line.pk, when=line.posted_at):
        entry = _post(ea, f"line:{line.pk}:withdrawal", "withdrawal", line,
                      [*_mandate_debits(ea, mandate, line.amount), cash], memo=mandate.reference)
        _resolve(line, Outcome.MATCHED, entry, mandate=mandate, note=reason)
        audit.record("system", "mandate.executed", mandate, {"line_id": line.pk})
        return
    entry = _post(ea, f"line:{line.pk}:withdrawal", "unexplained_outflow", line,
                  [Line(_acct(ea, P.UNEXPLAINED_OUT), D, line.amount), cash])
    _resolve(line, Outcome.UNMATCHED, entry, note=reason)
    alert = Alert.objects.create(
        group_id=ea.group_id, kind=Alert.Kind.UNMATCHED_OUTFLOW, line=line,
        message=(f"KES {line.amount} left the account on {line.posted_at:%d %b %Y} with no approved "
                 f"mandate. {reason}")[:255])
    audit.record("system", "alert.unmatched_outflow", alert, {"line_id": line.pk, "reason": reason})
    for member in _active_members(ea):
        outbox.emit("alert.unmatched_outflow", {
            "msisdn": member.person.msisdn, "group": ea.group.name, "amount": str(line.amount),
            "date": line.posted_at.date().isoformat(), "counterparty": line.counterparty_name,
            "alert_id": alert.pk})


# ---------------------------------------------------------------- corrections

def _latest(line) -> LineResolution:
    return line.resolutions.order_by("-id").first()


@transaction.atomic
def attribute_payment(line: StatementLine, membership: Membership, *, actor: str,
                      remember_payer: bool = True) -> LineResolution:
    """Assign an unattributed receipt to a member (the treasurer said who paid)."""
    ea = ExternalAccount.objects.select_for_update().get(pk=line.external_account_id)
    latest = _latest(line)
    if latest is None or latest.outcome != Outcome.UNATTRIBUTED:
        raise ConnectivityError("Only unattributed receipts can be attributed.")
    if membership.group_id != ea.group_id:
        raise ConnectivityError("That member belongs to another group.")
    entry = _post(ea, f"line:{line.pk}:attribute:{latest.pk}", "attribution", line, [
        Line(_acct(ea, P.UNATTRIBUTED_IN), D, line.amount),
        Line(_acct(ea, P.MEMBER_INTEREST, membership.pk), C, line.amount)])
    resolution = _resolve(line, Outcome.ATTRIBUTED, entry, membership=membership, actor=actor,
                          note="Attributed by treasurer")
    if remember_payer and line.counterparty_msisdn:
        try:
            PayerMapping.objects.get_or_create(
                group_id=ea.group_id, msisdn=normalize_msisdn(line.counterparty_msisdn),
                defaults={"membership": membership, "confirmed_by": actor})
        except ValidationError:
            pass
    audit.record(actor, "line.attributed", line, {"membership_id": membership.pk})
    return resolution


@transaction.atomic
def explain_outflow(line: StatementLine, mandate: Mandate, *, actor: str) -> LineResolution:
    """Link an unmatched outflow to a mandate approved after the fact."""
    ea = ExternalAccount.objects.select_for_update().get(pk=line.external_account_id)
    latest = _latest(line)
    if latest is None or latest.outcome != Outcome.UNMATCHED:
        raise ConnectivityError("Only unmatched outflows can be explained.")
    if mandate.fund_id != ea.fund_id or mandate.amount != line.amount:
        raise ConnectivityError("The mandate must be for this fund and exactly this amount.")
    if not claim_mandate(mandate.pk, line_id=line.pk, when=timezone.now()):
        raise ConnectivityError(f"Mandate {mandate.reference} is not available ({mandate.status}).")
    entry = _post(ea, f"line:{line.pk}:explain:{latest.pk}", "outflow_explained", line, [
        *_mandate_debits(ea, mandate, line.amount), Line(_acct(ea, P.UNEXPLAINED_OUT), C, line.amount)],
        memo=mandate.reference)
    resolution = _resolve(line, Outcome.EXPLAINED, entry, mandate=mandate, actor=actor,
                          note=f"Explained by mandate {mandate.reference}")
    Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW, line=line, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolution_note=f"Explained by mandate {mandate.reference} ({actor})")
    audit.record(actor, "line.explained", line, {"mandate": mandate.reference})
    return resolution


# ---------------------------------------------------------------- reconciliation

@transaction.atomic
def reconcile(ea: ExternalAccount) -> ReconciliationRun:
    """Compare WEPL's books with the custodian's statement and record the result."""
    ExternalAccount.objects.select_for_update().get(pk=ea.pk)
    lines = ea.lines.order_by("sequence")
    last = lines.exclude(running_balance__isnull=True).last()
    statement_balance = last.running_balance if last else None
    cash = ledger.balance(_acct(ea, P.CUSTODY_CASH))
    position = ledger.fund_position(ea.fund_id)
    sequences = [s for s in lines.exclude(kind=StatementLine.Kind.OPENING).values_list("sequence", flat=True)]
    gaps = sorted(set(range(min(sequences), max(sequences) + 1)) - set(sequences)) if sequences else []
    unresolved = lines.filter(resolutions__isnull=True).count()
    open_alerts = Alert.objects.filter(group_id=ea.group_id, resolved_at__isnull=True).count()
    difference = (cash - statement_balance) if statement_balance is not None else None
    balanced = (difference in (None, Decimal(0))) and not gaps and unresolved == 0
    run = ReconciliationRun.objects.create(
        external_account=ea, statement_balance=statement_balance, ledger_cash=cash, difference=difference,
        member_interests=position[P.MEMBER_INTEREST], unattributed=position[P.UNATTRIBUTED_IN],
        unexplained_out=position[P.UNEXPLAINED_OUT], retained=position[P.RETAINED],
        lines_seen=lines.count(), lines_unresolved=unresolved, sequence_gaps=gaps[:100],
        open_alerts=open_alerts, balanced=balanced)
    if not balanced:
        alert = Alert.objects.create(
            group_id=ea.group_id, kind=Alert.Kind.RECONCILIATION_DIFFERENCE,
            message=(f"Reconciliation {run.pk}: difference {difference}, gaps {gaps[:5]}, "
                     f"unresolved lines {unresolved}.")[:255])
        outbox.emit("ops.reconciliation_difference", {"run_id": run.pk, "alert_id": alert.pk})
    return run


def sync(ea: ExternalAccount, connector) -> tuple[IngestResult, ReconciliationRun]:
    """Fetch from the custodian, ingest, and reconcile."""
    result = ingest(ea, connector.fetch(ea.account_number))
    return result, reconcile(ea)
