"""Use cases: an official explains a line the system could not account for.
Corrections are new journal entries and new resolutions; nothing is edited."""
from django.db import transaction
from django.utils import timezone

from contexts.audit.public import operation, record
from contexts.communities.public import membership
from contexts.governance.public import MandateStatus, execute_mandate, mandate
from contexts.identity.public import Msisdn

from ..contract import CustodyError
from ..domain import accounting
from ..domain.resolution import InvalidCorrection, Outcome, ensure_correction
from ..infrastructure.models import Alert, ExternalAccount, LineResolution, PayerMapping, StatementLine
from . import bookkeeping as bk
from .authority import official


def _locked_line(line_id: int) -> tuple[ExternalAccount, StatementLine]:
    line = StatementLine.objects.select_related("external_account").get(pk=line_id)
    ea = ExternalAccount.objects.select_for_update().get(pk=line.external_account_id)
    return ea, line


@transaction.atomic  # entry, resolution, payer memory and audit commit together
def attribute_payment(line_id: int, membership_id: int, *, by: int, remember_payer: bool = True) -> LineResolution:
    """Credit an unattributed receipt to the member an official names. ``by``
    is the official's membership id; nobody may credit themselves."""
    ea, line = _locked_line(line_id)
    actor = official(by, ea.group_id, beneficiaries=[membership_id]).msisdn
    with operation("custody.attribute_payment", actor=actor):
        member = membership(membership_id)
        if member.group_id != ea.group_id:
            raise CustodyError("That member belongs to another group.")
        try:
            ensure_correction(bk.latest_outcome(line), Outcome.ATTRIBUTED)
        except InvalidCorrection as exc:
            raise CustodyError(f"Only unattributed receipts can be attributed. {exc}") from None
        count = line.resolutions.count()
        draft = accounting.payer_identified(bk.book(ea), key=f"line:{line.pk}:attribute:{count}", line_id=line.pk,
                                            amount=bk.amount(line), member_id=member.id)
        resolution = bk.post_and_resolve(line, draft, Outcome.ATTRIBUTED, membership_id=member.id, actor=actor,
                                         note="Attributed by an official")
        payer = Msisdn.try_parse(line.counterparty_msisdn)
        if remember_payer and payer is not None:
            PayerMapping.objects.get_or_create(group_id=ea.group_id, msisdn=payer.value,
                                               defaults={"membership_id": member.id, "confirmed_by": actor})
        record(actor, "custody.payment_attributed", target_type="statement_line", target_id=line.pk,
               group_id=ea.group_id, data={"membership_id": member.id})
        return resolution


@transaction.atomic  # the mandate claim, entry, resolution and alert closure commit together
def explain_outflow(line_id: int, mandate_id: int, *, by: int) -> LineResolution:
    """Tie an unmatched payout to a mandate approved after the fact. ``by`` is
    the official's membership id; the mandate itself carries the group's approval."""
    ea, line = _locked_line(line_id)
    actor = official(by, ea.group_id).msisdn
    with operation("custody.explain_outflow", actor=actor):
        m = mandate(mandate_id)
        try:
            ensure_correction(bk.latest_outcome(line), Outcome.EXPLAINED)
        except InvalidCorrection as exc:
            raise CustodyError(f"Only unmatched outflows can be explained. {exc}") from None
        if m.fund_id != ea.fund_id or m.amount != bk.amount(line):
            raise CustodyError("The mandate must be for this fund and exactly this amount.")
        if m.status is not MandateStatus.ISSUED or not execute_mandate(m.id, line_id=line.pk, when=timezone.now()):
            raise CustodyError(f"Mandate {m.reference} is not available ({m.status}).")
        ids, balances = bk.sharing_facts(ea)
        count = line.resolutions.count()
        draft = accounting.payout_explained(bk.book(ea), key=f"line:{line.pk}:explain:{count}", line_id=line.pk,
                                            amount=bk.amount(line), allocation=m.allocation,
                                            charged_member_id=m.charged_member_id, member_ids=ids, balances=balances,
                                            reference=m.reference)
        resolution = bk.post_and_resolve(line, draft, Outcome.EXPLAINED, mandate_id=m.id, actor=actor,
                                         note=f"Explained by mandate {m.reference}")
        Alert.objects.filter(kind=Alert.Kind.UNMATCHED_OUTFLOW, line=line, resolved_at__isnull=True).update(
            resolved_at=timezone.now(), resolution_note=f"Explained by mandate {m.reference} ({actor})")
        record(actor, "custody.outflow_explained", target_type="statement_line", target_id=line.pk,
               group_id=ea.group_id, data={"mandate": m.reference})
        return resolution
