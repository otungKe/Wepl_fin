"""Reserve the codes funds already used (ADR-0026): the one each fund holds
now and the ones it had before, from the audit trail. The earliest holder
keeps a code. Runs across every tenant: a migration has no tenant context."""
from django.db import migrations

from persistence.tenancy import CROSS_TENANT_OFF, CROSS_TENANT_ON

# Every code each fund has had: the ones set when it opened or changed later
# (audited since ADR-0023) and the one it holds now. The earliest holder keeps it.
BACKFILL = f"""
{CROSS_TENANT_ON}
INSERT INTO communities_fundcode (tenant_id, group_id, code, fund_id, first_used_at)
SELECT f.tenant_id, f.group_id, c.code, f.id, c.at
FROM (
    SELECT target_id::bigint AS fund_id, upper(data->>'code') AS code, created_at AS at
        FROM audit_auditevent WHERE action = 'fund.opened' AND target_type = 'fund' AND data ? 'code'
    UNION ALL
    SELECT target_id::bigint, upper(data->>'from'), created_at
        FROM audit_auditevent WHERE action = 'fund.code_set' AND target_type = 'fund' AND data->>'from' IS NOT NULL
    UNION ALL
    SELECT target_id::bigint, upper(data->>'to'), created_at
        FROM audit_auditevent WHERE action = 'fund.code_set' AND target_type = 'fund'
    UNION ALL
    SELECT id, code, created_at FROM communities_fund WHERE code IS NOT NULL
) c JOIN communities_fund f ON f.id = c.fund_id
ORDER BY c.at, f.id
ON CONFLICT (group_id, code) DO NOTHING;
{CROSS_TENANT_OFF}
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0017_fund_codes_reserved"), ("audit", "0003_tenant")]
    operations = [migrations.RunSQL(BACKFILL, migrations.RunSQL.noop)]
