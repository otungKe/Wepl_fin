"""ADR-0012: member codes are stable business identifiers.

- Each group hands out member sequence numbers from a counter that only
  increases, instead of counting its memberships.
- PostgreSQL refuses to delete a membership, to change its group, person,
  code or joining time, or to bring a membership that ended back to active.
  So a code can never be freed, reused or re-pointed at someone else.
  (Moving a row to another tenant is already refused by row-level security.)
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0005_remove_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="group",
            name="last_member_sequence",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
    ]


BACKFILL = """
SELECT set_config('app.cross_tenant', 'on', true);
UPDATE communities_group g SET last_member_sequence = coalesce(
    (SELECT max(substring(m.member_code FROM 2)::int) FROM communities_membership m WHERE m.group_id = g.id), 0);
SELECT set_config('app.cross_tenant', '', true);
"""

RULES = """
CREATE FUNCTION communities_membership_rules() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER communities_membership_rules_row BEFORE UPDATE OR DELETE ON communities_membership
    FOR EACH ROW EXECUTE FUNCTION communities_membership_rules();
CREATE TRIGGER communities_membership_rules_truncate BEFORE TRUNCATE ON communities_membership
    FOR EACH STATEMENT EXECUTE FUNCTION communities_membership_rules();

CREATE FUNCTION communities_group_sequence_rises() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.last_member_sequence < OLD.last_member_sequence THEN
        RAISE EXCEPTION 'member sequence numbers are never handed out twice'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_group_sequence_rises BEFORE UPDATE ON communities_group
    FOR EACH ROW EXECUTE FUNCTION communities_group_sequence_rises();
"""

UNDO_RULES = """
DROP TRIGGER IF EXISTS communities_group_sequence_rises ON communities_group;
DROP FUNCTION IF EXISTS communities_group_sequence_rises();
DROP TRIGGER IF EXISTS communities_membership_rules_truncate ON communities_membership;
DROP TRIGGER IF EXISTS communities_membership_rules_row ON communities_membership;
DROP FUNCTION IF EXISTS communities_membership_rules();
"""

Migration.operations += [migrations.RunSQL(BACKFILL, migrations.RunSQL.noop), migrations.RunSQL(RULES, UNDO_RULES)]
