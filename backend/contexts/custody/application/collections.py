"""Use cases for WEPL's pooled collection account (ADR-0018).

One bank account holds many groups' money. Each transaction is recorded once
as platform data, routed to exactly one group's fund sub-account (or held),
and then taken in by that group's ordinary ``ingest``, inside its own tenant.
Platform rows are visible only in a declared cross-tenant operation; group
rows only inside the group's tenant. The two phases never mix: a
cross-tenant operation cannot act for a tenant, and a tenant cannot see
platform data.

Held transactions and account-level differences are ``PoolAlert`` rows, the
operations inbox. Outbox notifications belong to one tenant, so none is sent
from here until WEPL has an operations channel."""
from dataclasses import dataclass
from decimal import Decimal

from contexts.audit.public import operation, record
from contexts.communities.public import fund_view, group_for_payment_code, group_view, members
from contexts.governance.public import mandates_by_reference
from contexts.tenancy.public import cross_tenant, tenant

from ..contract import CustodyError, ExternalAccountView
from ..domain.collections import RouteKind, parse_reference, route
from ..domain.matching import quoted_references
from ..domain.statement import BankLine, LineKind
from ..infrastructure.models import Collection, CollectionAccount, CollectionRouting, ExternalAccount, PoolAlert
from .accounts import link_external_account
from .ingestion import ingest

SYSTEM = "system"


@dataclass(frozen=True)
class ReferenceCheck:
    accepted: bool
    group_name: str = ""  # shown to the payer to confirm; never a member's name or phone
    reason: str = ""


@dataclass
class CollectionResult:
    new: int = 0
    duplicates: int = 0
    conflicts: int = 0
    routed: int = 0
    held: int = 0


def open_collection_account(*, institution: str, account_number: str, account_name: str, connector: str,
                            actor: str, currency: str = "KES") -> int:
    with cross_tenant("custody: open a pooled collection account", actor=actor):
        pool = CollectionAccount.objects.create(institution=institution, account_number=account_number,
                                                account_name=account_name, connector=connector, currency=currency)
        record(actor, "custody.collection_account_opened", target_type="collection_account", target_id=pool.pk,
               data={"institution": institution, "account_number": account_number})
        return pool.pk


def collect_into(fund_id: int, *, account_number: str, actor: str) -> ExternalAccountView:
    """Let a fund collect through the pooled account: it gets a sub-account
    there, named by the group's payment code. One per group per account."""
    with cross_tenant("custody: link a fund to the pooled collection account", actor=actor):
        pool = _pool(account_number)
        group = group_view(fund_view(fund_id).group_id)
        if ExternalAccount.objects.filter(pooled_in=pool, group_id=group.id).exists():
            raise CustodyError(f"{group.name} already collects through {account_number}.")
        pool_id, institution, currency = pool.pk, pool.institution, pool.currency
    with tenant(group.tenant_id):
        if fund_view(fund_id).currency != currency:
            raise CustodyError(f"The collection account holds {currency}.")
        return link_external_account(fund_id, institution=institution,
                                     account_number=f"{account_number}/{group.payment_code}",
                                     account_name=f"{group.name} via {account_number}", connector="collections",
                                     actor=actor, pooled_in=pool_id)


def check_reference(account_number: str, reference: str) -> ReferenceCheck:
    """The bank's question before it takes a payment: does this reference
    name an active member of a group that collects here? Read-only."""
    ref = parse_reference(reference)
    if ref is None:
        return ReferenceCheck(False, reason="Not a WEPL payment reference.")
    with cross_tenant("custody: check a payment reference for the bank", actor="bank"):
        pool = CollectionAccount.objects.filter(account_number=account_number).first()
        group = group_for_payment_code(ref.group_code) if pool else None
        if group is None or not ExternalAccount.objects.filter(pooled_in=pool, group_id=group.id).exists():
            return ReferenceCheck(False, reason="No group collects here with that payment code.")
        if not any(m.code == ref.member_code for m in members(group.id)):
            return ReferenceCheck(False, reason="No current member of the group has that member code.")
        return ReferenceCheck(True, group_name=group.name)


def receive(account_number: str, bank_lines) -> CollectionResult:
    """Take in transactions on the pooled account: record each once, route
    it, then hand each routed one to its group's ingest. Safe to repeat: a
    transaction seen before is delivered again, and ingest ignores it if its
    group already has it, so a crash between the phases heals on resend."""
    result, deliveries = CollectionResult(), []
    with operation("custody.collections", actor=SYSTEM):
        with cross_tenant("custody: record and route pooled collections", actor=SYSTEM):
            pool = CollectionAccount.objects.select_for_update().get(account_number=account_number)
            for bl in sorted(bank_lines, key=lambda l: l.sequence):
                delivery = _record_and_route(pool, bl, result)
                if delivery:
                    deliveries.append(delivery)
        for tenant_id, ea_id, line in deliveries:
            with tenant(tenant_id):
                ingest(ea_id, [line])
    return result


def open_pool_alerts(account_number: str) -> list[dict]:
    with cross_tenant("custody: read the operations inbox", actor=SYSTEM):
        return list(PoolAlert.objects.filter(account__account_number=account_number, resolved_at__isnull=True)
                    .order_by("id").values("id", "kind", "collection_id", "message"))


# -- inside the cross-tenant phase ------------------------------------------------------------------------------

def _pool(account_number: str) -> CollectionAccount:
    pool = CollectionAccount.objects.filter(account_number=account_number).first()
    if pool is None:
        raise CustodyError(f"Unknown collection account {account_number}.")
    return pool


def _record_and_route(pool: CollectionAccount, bl: BankLine, result: CollectionResult):
    existing = Collection.objects.filter(account=pool, external_id=bl.external_id).first()
    if existing is not None:
        if bl.same_fact_as(existing.kind, existing.amount, existing.sequence):
            result.duplicates += 1
            return _redelivery(existing)
        result.conflicts += 1
        _alert(pool, existing, PoolAlert.Kind.CONFLICT,
               f"Custodian resent {bl.external_id} with different details ({bl.kind} {bl.amount} vs "
               f"{existing.kind} {existing.amount}).")
        return None
    c = Collection.objects.create(
        account=pool, external_id=bl.external_id, sequence=bl.sequence, posted_at=bl.posted_at,
        kind=LineKind(bl.kind), amount=bl.amount, narration=bl.narration[:255], reference=bl.reference[:64],
        counterparty_name=bl.counterparty_name[:120], counterparty_msisdn=bl.counterparty_msisdn[:16],
        running_balance=bl.running_balance, metadata=bl.metadata)
    result.new += 1
    decision = route(kind=LineKind(bl.kind), reference=bl.reference,
                     quoted_mandates=tuple(quoted_references(bl.narration, bl.reference)))
    ea, reason = _sub_account(pool, decision)
    if ea is None:
        CollectionRouting.objects.create(collection=c, outcome="held", reason=reason[:255])
        _alert(pool, c, PoolAlert.Kind.HELD, f"{c.kind} {c.amount} ({c.external_id}) held: {reason}")
        result.held += 1
        return None
    previous = (CollectionRouting.objects.filter(external_account_id=ea.pk, outcome="routed")
                .order_by("-sub_sequence").values_list("sub_sequence", "sub_balance").first()) or (0, Decimal(0))
    r = CollectionRouting.objects.create(
        collection=c, outcome="routed", routed_to_tenant=ea.tenant_id, external_account_id=ea.pk,
        sub_sequence=previous[0] + 1, sub_balance=previous[1] + signed(c.kind, c.amount),
        reason=f"{decision.kind.value} {decision.key}")
    result.routed += 1
    return _delivery(c, r, member_code=decision.member_code)


def _sub_account(pool: CollectionAccount, decision) -> tuple[ExternalAccount | None, str]:
    if decision.kind == RouteKind.BY_PAYMENT_CODE:
        group = group_for_payment_code(decision.key)
        ea = ExternalAccount.objects.filter(pooled_in=pool, group_id=group.id).first() if group else None
        return ea, "" if ea else f"No group collects here with payment code {decision.key}."
    if decision.kind == RouteKind.BY_MANDATE:
        found = mandates_by_reference([decision.key])
        ea = ExternalAccount.objects.filter(pooled_in=pool, fund_id=found[0].fund_id).first() if found else None
        return ea, "" if ea else f"Mandate {decision.key} is not for a fund collecting here."
    return None, decision.reason


def _redelivery(c: Collection):
    r = c.routings.filter(outcome="routed").first()
    return _delivery(c, r, member_code=parse_reference(c.reference).member_code
                     if c.kind == LineKind.DEPOSIT and parse_reference(c.reference) else "") if r else None


def _delivery(c: Collection, r: CollectionRouting, *, member_code: str):
    """The line as the group's sub-account sees it: its own numbering and
    balance, and for a pay-in the member code alone as the reference, so
    attribution reads it as it reads any statement."""
    line = BankLine(external_id=c.external_id, sequence=r.sub_sequence, posted_at=c.posted_at, kind=LineKind(c.kind),
                    amount=c.amount, narration=c.narration, reference=member_code or c.reference,
                    counterparty_name=c.counterparty_name, counterparty_msisdn=c.counterparty_msisdn,
                    running_balance=r.sub_balance,
                    metadata={**c.metadata, "pooled": {"collection_id": c.pk, "sequence": c.sequence,
                                                       "reference": c.reference}})
    return r.routed_to_tenant, r.external_account_id, line


def _alert(pool, c, kind, message):
    PoolAlert.objects.get_or_create(account=pool, kind=kind, collection=c, defaults={"message": message[:255]})
    record(SYSTEM, f"custody.pool_{kind}", target_type="collection", target_id=c.pk, data={"message": message[:255]})


def signed(kind, amount) -> Decimal:
    return Decimal(amount) if LineKind(kind).is_inflow else -Decimal(amount)

