"""Use cases: a member granted correct_records explains a line the system could not account for.
Corrections are new journal entries and new resolutions; nothing is edited."""
from django.db import transaction
from django.utils import timezone

from contexts.audit.public import operation, record
from contexts.communities.public import CommunityError, fund_view, hold_open_fund, membership
from contexts.governance.public import MandateStatus, committed_out, execute_mandate, mandate, shortfall
from contexts.identity.public import Msisdn
from contexts.ledger.public import account_balance, cash_by_fund, entry_credits
from contexts.shared_kernel.money import Money

from ..contract import CustodyError, LineKind
from ..domain import accounting
from ..domain.resolution import InvalidCorrection, Outcome, ensure_correction
from ..domain.sharing import Event
from ..infrastructure.models import Alert, ExternalAccount, LineResolution, PayerMapping, StatementLine
from . import bookkeeping as bk
from .authority import corrector


def _locked_line(line_id: int) -> tuple[ExternalAccount, StatementLine]:
    line = StatementLine.objects.select_related("external_account").get(pk=line_id)
    ea = ExternalAccount.objects.select_for_update().get(pk=line.external_account_id)
    return ea, line


@transaction.atomic  # entry, resolution, payer memory and audit commit together
def attribute_payment(line_id: int, membership_id: int, *, by: int, remember_payer: bool = True) -> LineResolution:
    """Credit an unattributed receipt to the member a corrector names. ``by``
    is the corrector's membership id; nobody may credit themselves."""
    ea, line = _locked_line(line_id)
    actor = corrector(by, ea.group_id, beneficiaries=[membership_id]).msisdn
    with operation("custody.attribute_payment", actor=actor):
        member = bk.member_of(ea.group_id, membership_id)
        try:
            ensure_correction(bk.latest_outcome(line), Outcome.ATTRIBUTED)
        except InvalidCorrection as exc:
            raise CustodyError(f"Only unattributed receipts can be attributed. {exc}") from None
        count = line.resolutions.count()
        held_in = bk.line_fund(line)  # the fund the pay-in went to (ADR-0023); it stays there
        draft = accounting.payer_identified(bk.book(ea, held_in), key=f"line:{line.pk}:attribute:{count}", line_id=line.pk,
                                            amount=bk.amount(line), member_id=member.id,
                                            fine=bk.takes_fines(ea, held_in))
        resolution = bk.post_and_resolve(line, draft, Outcome.ATTRIBUTED, membership_id=member.id, actor=actor,
                                         note="Attributed by a corrector")
        payer = Msisdn.try_parse(line.counterparty_msisdn)
        if remember_payer and payer is not None and member.is_active:
            _remember(ea.group_id, payer.value, member.id, actor)
        record(actor, "custody.payment_attributed", target_type="statement_line", target_id=line.pk,
               group_id=ea.group_id, data={"membership_id": member.id})
        return resolution


def _remember(group_id: int, msisdn: str, membership_id: int, actor: str) -> None:
    """Remember who this payer pays for. A number remembered for a spell that
    has since ended now means the member's current spell (ADR-0012); one
    remembered for a current spell is left as it is."""
    mapping, created = PayerMapping.objects.get_or_create(
        group_id=group_id, msisdn=msisdn, defaults={"membership_id": membership_id, "confirmed_by": actor})
    if not created and mapping.membership_id != membership_id and not membership(mapping.membership_id).is_active:
        mapping.membership_id, mapping.confirmed_by = membership_id, actor
        mapping.save(update_fields=["membership", "confirmed_by"])


@transaction.atomic  # the mandate claim, entry, resolution and alert closure commit together
def explain_outflow(line_id: int, mandate_id: int, *, by: int) -> LineResolution:
    """Tie an unmatched payout to a mandate approved after the fact. ``by`` is
    the corrector's membership id; the mandate itself carries the group's approval."""
    ea, line = _locked_line(line_id)
    actor = corrector(by, ea.group_id).msisdn
    with operation("custody.explain_outflow", actor=actor):
        m = mandate(mandate_id)
        try:
            ensure_correction(bk.latest_outcome(line), Outcome.EXPLAINED)
        except InvalidCorrection as exc:
            raise CustodyError(f"Only unmatched outflows can be explained. {exc}") from None
        if m.group_id != ea.group_id or m.amount != bk.amount(line):
            raise CustodyError("The mandate must be this group's and for exactly this amount.")
        if m.status is not MandateStatus.ISSUED or not execute_mandate(m.id, line_id=line.pk, when=timezone.now()):
            raise CustodyError(f"Mandate {m.reference} is not available ({m.status}).")
        ids, balances = bk.sharing_facts(ea, m.fund_id, at=line.posted_at, event=Event.PAYOUT,
                                         approved_at=m.issued_at)
        resolution = _explain(ea, line, m, ids, balances, actor)
        Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW, line=line, resolved_at__isnull=True).update(
            resolved_at=timezone.now(), resolution_note=f"Explained by mandate {m.reference} ({actor})")
        record(actor, "custody.outflow_explained", target_type="statement_line", target_id=line.pk,
               group_id=ea.group_id, data={"mandate": m.reference})
        return resolution


def _explain(ea, line, m, ids, balances, actor) -> LineResolution:
    """Post the explanation in the mandate's fund. The outflow was held as
    unexplained in the fund it was posted to; when the mandate spends another
    fund of the same account, that fund gets its cash back first (ADR-0023)."""
    held_in, count, note = bk.line_fund(line), line.resolutions.count(), f"Explained by mandate {m.reference}"
    terms = dict(key=f"line:{line.pk}:explain:{count}", line_id=line.pk, amount=bk.amount(line),
                 allocation=m.allocation, charged_member_id=m.charged_member_id, member_ids=ids, balances=balances,
                 reference=m.reference)
    if held_in == m.fund_id:
        return bk.post_and_resolve(line, accounting.payout_explained(bk.book(ea, held_in), **terms),
                                   Outcome.EXPLAINED, mandate_id=m.id, actor=actor, note=note)
    back, paid = accounting.payout_explained_elsewhere(bk.book(ea, held_in), bk.book(ea, m.fund_id), **terms)
    bk.post_and_resolve(line, back, Outcome.EXPLAINED, mandate_id=m.id, actor=actor,
                        note=f"Moved to the fund mandate {m.reference} spends")
    return bk.post_and_resolve(line, paid, Outcome.EXPLAINED, mandate_id=m.id, actor=actor, note=note)


@transaction.atomic  # the fund lock, both entries, both resolutions and the audit commit together
def move_pay_in(line_id: int, fund_id: int, *, by: int, reason: str) -> LineResolution:
    """Book a pay-in in the fund it was meant for, when it went to another fund
    of the same bank account, e.g. the payer left out the fund code (ADR-0025).
    The money keeps its owner: the member it was credited to, or nobody yet if
    it is still unattributed. ``by`` is the corrector's membership id; nobody
    may move their own pay-in. It moves only while the money is still in the
    fund it went to and not promised out of it."""
    ea, line = _locked_line(line_id)
    last = line.resolutions.order_by("-id").first()
    member_id = last.membership_id if last else None
    actor = corrector(by, ea.group_id, beneficiaries=[member_id] if member_id else []).msisdn
    with operation("custody.move_pay_in", actor=actor):
        if LineKind(line.kind) is not LineKind.DEPOSIT:
            raise CustodyError("Only a pay-in can be moved to another fund.")
        try:
            ensure_correction(Outcome(last.outcome) if last else None, Outcome.MOVED)
        except InvalidCorrection as exc:
            raise CustodyError(f"Only a pay-in credited to a member or held as unattributed can move. {exc}") from None
        if not reason.strip():
            raise CustodyError("Say why the pay-in belongs in the other fund.")
        held_in = bk.line_fund(line)
        if fund_id == held_in:
            raise CustodyError("The pay-in is already in that fund.")
        right = _fund_of(ea, fund_id)
        wrong = fund_view(held_in)
        (owner, _), = entry_credits(last.journal_entry_id)  # whoever the pay-in's latest entry credited
        amount = bk.amount(line)
        if why := shortfall(amount, owners_hold=account_balance(owner),
                            cash=cash_by_fund(ea.pk, ea.currency).get(held_in, Money.zero(ea.currency)),
                            committed=committed_out(held_in)):
            raise CustodyError(f"The pay-in can no longer move out of {wrong.name}: {why}.")
        out, into = accounting.pay_in_moved(
            bk.book(ea, held_in), bk.book(ea, right.id), key=f"line:{line.pk}:move:{line.resolutions.count()}",
            line_id=line.pk, amount=amount, owner=owner, member_id=member_id, fine=bk.takes_fines(ea, right.id),
            memo_out=f"Moved to {right.name}", memo_in=f"Moved from {wrong.name}")
        bk.post_and_resolve(line, out, Outcome.MOVED, membership_id=member_id, actor=actor,
                            note=f"Moved to {right.name}: {reason.strip()}")
        resolution = bk.post_and_resolve(line, into, Outcome(last.outcome), membership_id=member_id, actor=actor,
                                         note=f"Moved from {wrong.name}: {reason.strip()}")
        _settle_unclear_code(line, f"Moved to {right.name} ({actor})")
        record(actor, "custody.pay_in_moved", target_type="statement_line", target_id=line.pk, group_id=ea.group_id,
               data={"from_fund_id": held_in, "to_fund_id": right.id, "membership_id": member_id,
                     "reason": reason.strip()[:500]})
        return resolution


@transaction.atomic
def keep_pay_in(line_id: int, *, by: int, reason: str) -> None:
    """Confirm that a pay-in whose reference named no one fund belongs in the
    fund it went to, and close its alert (ADR-0026). Nothing is posted. ``by``
    is the corrector's membership id. To put it in another fund, use
    ``move_pay_in`` instead, which closes the alert too."""
    ea, line = _locked_line(line_id)
    actor = corrector(by, ea.group_id).msisdn
    if not reason.strip():
        raise CustodyError("Say why the pay-in stays where it is.")
    with operation("custody.keep_pay_in", actor=actor):
        if not _settle_unclear_code(line, f"Kept in {fund_view(bk.line_fund(line)).name} ({actor}): {reason.strip()}"):
            raise CustodyError("This pay-in has no open question about its fund.")
        record(actor, "custody.pay_in_kept", target_type="statement_line", target_id=line.pk, group_id=ea.group_id,
               data={"fund_id": bk.line_fund(line), "reason": reason.strip()[:500]})


def _settle_unclear_code(line: StatementLine, note: str) -> int:
    return Alert.objects.filter(kind=Alert.Kind.FUND_CODE_UNCLEAR, line=line, resolved_at__isnull=True).update(
        resolved_at=timezone.now(), resolution_note=note[:255])


def _fund_of(ea: ExternalAccount, fund_id: int):
    """An open fund of the account's group, locked against closing until this
    correction commits."""
    try:
        f = hold_open_fund(fund_id)
    except CommunityError as exc:
        raise CustodyError(f"The pay-in cannot move there: {exc}") from None
    if f.group_id != ea.group_id or f.currency != ea.currency:
        raise CustodyError("The pay-in can move only to another fund of this group, in the account's currency.")
    return f
