"""ADR-0013.

- Segment leaves the core model. It was pilot research metadata, which the
  pilot tracker keeps per group.
- PostgreSQL allocates the member sequence on every insert. It takes the
  group's counter under the group row lock and refuses any code other than
  the one that number formats to, so no path (use case, admin tool, worker,
  raw SQL) can skip, reuse or reorder a code. ``member_code()`` in the
  domain is the formatter; this only checks its output: M01..M99, then
  M100 and up.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("communities", "0006_member_sequence"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="group",
            name="segment",
        ),
    ]


ALLOCATE = """
CREATE FUNCTION communities_membership_allocate() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    seq integer;
BEGIN
    UPDATE communities_group SET last_member_sequence = last_member_sequence + 1
        WHERE id = NEW.group_id RETURNING last_member_sequence INTO seq;
    IF seq IS NULL THEN
        RAISE EXCEPTION 'membership for an unknown group' USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NEW.member_code IS DISTINCT FROM 'M' || lpad(seq::text, greatest(2, length(seq::text)), '0') THEN
        RAISE EXCEPTION 'member code % is not the next in this group (M%)', NEW.member_code, seq
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER communities_membership_allocate BEFORE INSERT ON communities_membership
    FOR EACH ROW EXECUTE FUNCTION communities_membership_allocate();
"""

UNDO_ALLOCATE = """
DROP TRIGGER IF EXISTS communities_membership_allocate ON communities_membership;
DROP FUNCTION IF EXISTS communities_membership_allocate();
"""

Migration.operations += [migrations.RunSQL(ALLOCATE, UNDO_ALLOCATE)]
