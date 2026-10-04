"""The operator inbox: every open problem in every group.

WEPL's operators are not a tenant (ADR-0010). The inbox is a declared,
audited job that acts for each tenant in turn, reading only that tenant's
own rows through each context's public surface, so no query ever sees two
groups at once."""
from django.utils import timezone

from contexts.communities.public import groups
from contexts.custody.public import accounts_for_group, latest_reconciliation, open_alerts
from contexts.ledger.public import latest_checks
from contexts.tenancy.public import tenant, tenant_ids

from ..domain.inbox import InboxItem, ItemKind, is_stale, ordered


def operator_inbox(*, actor: str) -> list[InboxItem]:
    items = []
    for tenant_id in tenant_ids(reason="operator inbox: open problems in every group", actor=actor):
        with tenant(tenant_id):
            for g in groups():
                items += _for_group(g.id, g.name)
    return ordered(items)


def _for_group(group_id: int, name: str) -> list[InboxItem]:
    now, items = timezone.now(), []
    for a in open_alerts(group_id):
        items.append(InboxItem(group_id, name, ItemKind(a["kind"]), a.get("created_at"), a["message"]))
    for ea in accounts_for_group(group_id):
        last = latest_reconciliation(ea.id)
        if is_stale(last.run_at if last else None, now):
            items.append(InboxItem(group_id, name, ItemKind.NOT_RECONCILED, last.run_at if last else None,
                                   f"{ea} has not been reconciled since "
                                   f"{f'{last.run_at:%d %b %Y %H:%M}' if last else 'it was linked'}."))
    for c in latest_checks():
        if not c["passed"]:
            items.append(InboxItem(group_id, name, ItemKind.BOOKS_FAILED, c["checked_at"],
                                   f"Fund {c['fund_id']} ({c['currency']}) failed its integrity check."))
    return items
