"""The bank's collections service on a group's own account (ADR-0019).

Each chama account can have the service. The bank asks WEPL whether a
payment reference is good before it takes the money, then tells WEPL about
each payment as it happens. The account the payment went to names the group,
so nothing is routed between groups: the notification goes to that group's
ordinary ``ingest``, inside its own tenant.

Finding the account from its number is the one cross-tenant step. It reads
only which tenant holds that account, then acts inside it."""
from dataclasses import dataclass

from contexts.communities.public import group_view, members
from contexts.tenancy.public import cross_tenant, tenant

from ..contract import IngestResult
from ..domain.attribution import quoted_msisdn
from ..domain.routing import fund_for, quoted_codes, unknown_words
from ..infrastructure.models import ExternalAccount
from .ingestion import fund_codes, ingest

CONNECTOR = "business_connect"


@dataclass(frozen=True)
class ReferenceCheck:
    accepted: bool
    group_name: str = ""  # shown to the payer to confirm; never a member's name or phone
    reason: str = ""


def check_reference(account_number: str, reference: str) -> ReferenceCheck:
    """Does this reference name a current member of the group whose account
    it is: their mobile number or their member code, with or without one of
    the group's fund codes (ADR-0023)? Read-only."""
    found = _account(account_number)
    if found is None:
        return ReferenceCheck(False, reason="No WEPL group collects into that account.")
    ea_id, tenant_id = found
    with tenant(tenant_id):
        ea = ExternalAccount.objects.get(pk=ea_id)
        codes = fund_codes(ea.group_id)
        if unknown := unknown_words(reference, codes):
            return ReferenceCheck(False, reason=f"{unknown[0]} is not the code of one of this group's funds.")
        if len({codes[c] for c in quoted_codes(reference, codes)}) > 1:
            return ReferenceCheck(False, reason="Quote the code of one fund only.")
        reference = fund_for(reference, codes, ea.fund_id)[1]
        current = members(ea.group_id)
        number = quoted_msisdn(reference)
        named = [m for m in current if m.msisdn == number] if number else \
            [m for m in current if m.code.upper() == reference.strip().upper()]
        if not named:
            return ReferenceCheck(False, reason="Not the mobile number or code of a current member of this group.")
        return ReferenceCheck(True, group_name=group_view(ea.group_id).name)


def receive(account_number: str, bank_lines) -> IngestResult:
    """Payments the bank notified, taken in by the group's own ingest: a
    resend is ignored, a resend with different details raises an alert."""
    found = _account(account_number)
    if found is None:
        raise UnknownAccount(account_number)
    ea_id, tenant_id = found
    with tenant(tenant_id):
        return ingest(ea_id, bank_lines)


class UnknownAccount(LookupError):
    pass


def _account(account_number: str) -> tuple[int, int] | None:
    with cross_tenant("custody: find the group whose account the bank named", actor="bank"):
        rows = list(ExternalAccount.objects.filter(account_number=account_number, connector=CONNECTOR,
                                                   closed_at__isnull=True)
                    .values_list("pk", "tenant_id")[:2])
    return rows[0] if len(rows) == 1 else None
