"""A pay-in booked in the wrong fund can be moved to the fund it was meant
for (ADR-0025). The move is two resolutions of the line: ``moved`` (the
entry taking it out of the wrong fund), then the entry booking it in the
right one, with the line's outcome as it was.

PostgreSQL holds the pair together: at commit, a ``moved`` resolution must be
on a pay-in and be followed at once by an ``attributed`` or ``unattributed``
resolution for the same member (or for nobody), so no code path can commit
money taken out of one fund without putting it into another."""

from django.db import migrations, models

PAIR_RULE = """
CREATE FUNCTION custody_move_completed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    nxt record;
    outer_tenant text := current_setting('app.tenant_id', true);
BEGIN
    -- Deferred to commit, maybe after the tenant context ended: read as the row's tenant.
    PERFORM set_config('app.tenant_id', NEW.tenant_id::text, true);
    IF (SELECT kind FROM custody_statementline WHERE id = NEW.line_id) IS DISTINCT FROM 'deposit' THEN
        RAISE EXCEPTION 'line % is not a pay-in; only a pay-in moves between funds', NEW.line_id
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT outcome, membership_id INTO nxt FROM custody_lineresolution
     WHERE line_id = NEW.line_id AND id > NEW.id ORDER BY id LIMIT 1;
    IF nxt.outcome IS NULL OR nxt.outcome NOT IN ('attributed', 'unattributed')
       OR nxt.membership_id IS DISTINCT FROM NEW.membership_id THEN
        RAISE EXCEPTION 'pay-in % was taken out of a fund and not booked in another for the same owner', NEW.line_id
            USING ERRCODE = 'check_violation';
    END IF;
    PERFORM set_config('app.tenant_id', coalesce(outer_tenant, ''), true);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER custody_move_completed
    AFTER INSERT ON custody_lineresolution DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.outcome = 'moved')
    EXECUTE FUNCTION custody_move_completed();
"""

UNDO_PAIR_RULE = """
DROP TRIGGER IF EXISTS custody_move_completed ON custody_lineresolution;
DROP FUNCTION IF EXISTS custody_move_completed();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("custody", "0008_one_account_holds_the_groups_funds"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lineresolution",
            name="outcome",
            field=models.CharField(
                choices=[
                    ("attributed", "attributed"),
                    ("unattributed", "unattributed"),
                    ("interest", "interest"),
                    ("charge", "charge"),
                    ("matched", "matched"),
                    ("unmatched", "unmatched"),
                    ("explained", "explained"),
                    ("opening", "opening"),
                    ("moved", "moved"),
                ],
                max_length=14,
            ),
        ),
        migrations.RunSQL(PAIR_RULE, UNDO_PAIR_RULE),
    ]
