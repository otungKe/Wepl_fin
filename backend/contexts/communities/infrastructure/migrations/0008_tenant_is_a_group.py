"""Review of 2026-09-30 (docs/architecture/review-communities-membership.md).

- A tenant is a group (ADR-0010, ADR-0013): a deferred check refuses to
  commit a tenant that has no group, so "a tenant containing a group" cannot
  be built by provisioning a bare tenant. It reads under the new tenant's own
  id, because row-level security would otherwise hide the group at commit.
- Only allocation moves a group's member counter: it starts at 0, and
  changes only from inside the membership insert trigger, so no update by
  hand can skip codes.
"""
from django.db import migrations

TENANT_IS_A_GROUP = """
CREATE FUNCTION communities_tenant_is_a_group() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    outer_tenant text := current_setting('app.tenant_id', true);
    has_group boolean;
BEGIN
    PERFORM set_config('app.tenant_id', NEW.id::text, true);
    SELECT EXISTS (SELECT 1 FROM communities_group WHERE tenant_id = NEW.id) INTO has_group;
    PERFORM set_config('app.tenant_id', coalesce(outer_tenant, ''), true);
    IF NOT has_group THEN
        RAISE EXCEPTION 'tenant % has no group: a tenant is a group, founded with create_group', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER communities_tenant_is_a_group AFTER INSERT ON tenancy_tenant
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION communities_tenant_is_a_group();
"""

UNDO_TENANT_IS_A_GROUP = """
DROP TRIGGER IF EXISTS communities_tenant_is_a_group ON tenancy_tenant;
DROP FUNCTION IF EXISTS communities_tenant_is_a_group();
"""

ONLY_ALLOCATION_MOVES_THE_COUNTER = """
DROP TRIGGER IF EXISTS communities_group_sequence_rises ON communities_group;
CREATE OR REPLACE FUNCTION communities_group_sequence_rises() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.last_member_sequence <> 0 THEN
            RAISE EXCEPTION 'a new group starts at member sequence 0' USING ERRCODE = 'restrict_violation';
        END IF;
    ELSIF NEW.last_member_sequence IS DISTINCT FROM OLD.last_member_sequence THEN
        -- depth 1 is a statement from the application; the allocation trigger runs one level deeper
        IF pg_trigger_depth() < 2 OR NEW.last_member_sequence <> OLD.last_member_sequence + 1 THEN
            RAISE EXCEPTION 'only joining a member moves the member sequence' USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_group_sequence_rises BEFORE INSERT OR UPDATE ON communities_group
    FOR EACH ROW EXECUTE FUNCTION communities_group_sequence_rises();
"""


class Migration(migrations.Migration):
    dependencies = [("communities", "0007_remove_segment_db_allocates_codes"), ("tenancy", "0001_initial")]
    operations = [migrations.RunSQL(TENANT_IS_A_GROUP, UNDO_TENANT_IS_A_GROUP),
                  migrations.RunSQL(ONLY_ALLOCATION_MOVES_THE_COUNTER, migrations.RunSQL.noop)]
