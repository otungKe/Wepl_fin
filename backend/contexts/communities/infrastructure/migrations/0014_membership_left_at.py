"""When a membership spell ended (ADR-0014). Leaving stays a non-financial
fact, but a group whose rule freezes leavers' balances needs to know which
bank events came after it. Set by leave_group; set exactly when the spell is
left; never changed once set."""
from django.db import migrations, models

from persistence.tenancy import CROSS_TENANT_OFF, CROSS_TENANT_ON

# Every tenant's memberships, so the step runs cross-tenant: a migration has
# no tenant context and would otherwise see no rows (persistence/tenancy.py).
# A spell that ended before this column existed takes the time of its
# member.left audit record, or its joining time if none was kept.
BACKFILL = f"""
{CROSS_TENANT_ON}
UPDATE communities_membership m SET left_at = coalesce(
    (SELECT min(a.created_at) FROM audit_auditevent a
     WHERE a.action = 'member.left' AND a.target_type = 'membership' AND a.target_id = m.id::text),
    m.joined_at)
WHERE m.status = 'left' AND m.left_at IS NULL;
{CROSS_TENANT_OFF}
"""

RULES = """
CREATE OR REPLACE FUNCTION communities_membership_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'memberships are never deleted: % is not allowed', TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.group_id, NEW.person_id, NEW.member_code, NEW.joined_at)
       IS DISTINCT FROM (OLD.group_id, OLD.person_id, OLD.member_code, OLD.joined_at) THEN
        RAISE EXCEPTION 'a membership''s group, person, code and joining time never change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'left' AND NEW.status <> 'left' THEN
        RAISE EXCEPTION 'a membership that ended stays ended; a returning member joins again'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.left_at IS NOT NULL AND NEW.left_at IS DISTINCT FROM OLD.left_at THEN
        RAISE EXCEPTION 'when a membership ended never changes' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
ALTER TABLE communities_membership ADD CONSTRAINT communities_left_at_iff_left
    CHECK ((status = 'left') = (left_at IS NOT NULL));
"""

UNDO_RULES = """
ALTER TABLE communities_membership DROP CONSTRAINT IF EXISTS communities_left_at_iff_left;
CREATE OR REPLACE FUNCTION communities_membership_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'UPDATE' THEN
        RAISE EXCEPTION 'memberships are never deleted: % is not allowed', TG_OP
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.group_id, NEW.person_id, NEW.member_code, NEW.joined_at)
       IS DISTINCT FROM (OLD.group_id, OLD.person_id, OLD.member_code, OLD.joined_at) THEN
        RAISE EXCEPTION 'a membership''s group, person, code and joining time never change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'left' AND NEW.status <> 'left' THEN
        RAISE EXCEPTION 'a membership that ended stays ended; a returning member joins again'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0013_linked_rows_keep_their_tenant"), ("audit", "0003_tenant")]
    operations = [
        migrations.AddField(model_name="membership", name="left_at",
                            field=models.DateTimeField(blank=True, null=True, editable=False)),
        migrations.RunSQL(BACKFILL, migrations.RunSQL.noop),
        migrations.RunSQL(RULES, UNDO_RULES),
    ]
