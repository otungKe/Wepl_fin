"""Communities review of 2026-10-06 (C3, I5; ADR-0026).

- A fund's status is OPEN or CLOSED and a membership's ACTIVE or LEFT, and
  nothing else. The lifecycle triggers refuse leaving 'closed' and 'left';
  without these checks a raw write could step around them through a third
  value ('archived', 'suspended'), and around the close guards of governance
  and custody, which fire on 'closed' only.
- A spell ends no earlier than it began.
- An ended spell's title is history: only an active membership's changes.
- A group never moves to another tenant: the group is its tenant (ADR-0010).
A CHECK is validated by PostgreSQL itself over every row, whatever the tenant
context, so adding these needs no cross-tenant step.
"""
from django.db import migrations, models

MEMBERSHIP_RULES = """
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
    IF OLD.status = 'left' AND NEW.title IS DISTINCT FROM OLD.title THEN
        RAISE EXCEPTION 'an ended membership''s title is history' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION communities_group_rules() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'a group is its tenant; it never moves to another' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_group_rules BEFORE UPDATE ON communities_group
    FOR EACH ROW EXECUTE FUNCTION communities_group_rules();
"""

PREVIOUS_RULES = """
DROP TRIGGER IF EXISTS communities_group_rules ON communities_group;
DROP FUNCTION IF EXISTS communities_group_rules();
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
"""


class Migration(migrations.Migration):

    dependencies = [("communities", "0015_fund_codes")]

    operations = [
        migrations.AddConstraint(
            model_name="fund",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["open", "closed"])),
                                              name="community_fund_status"),
        ),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.CheckConstraint(condition=models.Q(("status__in", ["active", "left"])),
                                              name="community_membership_status"),
        ),
        migrations.AddConstraint(
            model_name="membership",
            constraint=models.CheckConstraint(
                condition=models.Q(("left_at__isnull", True), ("left_at__gte", models.F("joined_at")),
                                   _connector="OR"),
                name="community_left_after_joining"),
        ),
        migrations.RunSQL(MEMBERSHIP_RULES, PREVIOUS_RULES),
    ]
