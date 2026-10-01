"""ADR-0017: every governance row names groups, funds, members, constitutions
and proposals of its own tenant only, as keys PostgreSQL checks for any role
in any mode. Proposals, mandates and constitutions can be referred to by
(id, tenant) in turn."""
from django.db import migrations

from persistence.tenancy import same_tenant, tenant_keyed

GROUP, FUND, MEMBERSHIP = "communities_group", "communities_fund", "communities_membership"


class Migration(migrations.Migration):
    dependencies = [("governance", "0005_closed_funds"), ("communities", "0013_linked_rows_keep_their_tenant")]
    operations = [migrations.RunSQL(*sql) for sql in (
        tenant_keyed("governance_constitution"),
        tenant_keyed("governance_proposal"),
        tenant_keyed("governance_mandate"),
        same_tenant("governance_constitution", "group_id", GROUP),
        same_tenant("governance_proposal", "group_id", GROUP),
        same_tenant("governance_proposal", "fund_id", FUND),
        same_tenant("governance_proposal", "constitution_id", "governance_constitution"),
        same_tenant("governance_proposal", "proposed_by_id", MEMBERSHIP),
        same_tenant("governance_proposal", "charged_member_id", MEMBERSHIP),
        same_tenant("governance_approval", "proposal_id", "governance_proposal"),
        same_tenant("governance_approval", "membership_id", MEMBERSHIP),
        same_tenant("governance_mandate", "proposal_id", "governance_proposal"),
        same_tenant("governance_mandate", "group_id", GROUP),
        same_tenant("governance_mandate", "fund_id", FUND),
        same_tenant("governance_mandate", "charged_member_id", MEMBERSHIP),
        same_tenant("governance_capabilitychange", "group_id", GROUP),
        same_tenant("governance_capabilitychange", "membership_id", MEMBERSHIP),
    )]
