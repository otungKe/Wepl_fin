"""A fund closes only when governance has nothing pending on it, and a closed
fund takes no new proposal (fund lifecycle, ADR-0015).

Governance owns this rule, so it lives here, on the side that already
depends on communities. A new proposal takes a share lock on its fund, and
closing updates the fund row, so the two serialise: whichever commits first,
the other sees it.
"""
from django.db import migrations

FORWARD = """
CREATE FUNCTION governance_fund_may_close() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'closed' AND OLD.status IS DISTINCT FROM 'closed' AND (
        EXISTS (SELECT 1 FROM governance_proposal WHERE fund_id = NEW.id AND status = 'open')
        OR EXISTS (SELECT 1 FROM governance_mandate WHERE fund_id = NEW.id AND status = 'issued')) THEN
        RAISE EXCEPTION 'fund % has an open proposal or an unexecuted mandate; settle it before closing', NEW.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER governance_fund_may_close BEFORE UPDATE OF status ON communities_fund
    FOR EACH ROW EXECUTE FUNCTION governance_fund_may_close();

CREATE FUNCTION governance_proposal_on_open_fund() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT status FROM communities_fund WHERE id = NEW.fund_id FOR SHARE) IS DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'fund % is closed', NEW.fund_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER governance_proposal_on_open_fund BEFORE INSERT ON governance_proposal
    FOR EACH ROW EXECUTE FUNCTION governance_proposal_on_open_fund();
"""

REVERSE = """
DROP TRIGGER IF EXISTS governance_proposal_on_open_fund ON governance_proposal;
DROP FUNCTION IF EXISTS governance_proposal_on_open_fund();
DROP TRIGGER IF EXISTS governance_fund_may_close ON communities_fund;
DROP FUNCTION IF EXISTS governance_fund_may_close();
"""


class Migration(migrations.Migration):
    dependencies = [("governance", "0004_capabilitychange"), ("communities", "0012_fund_lifecycle")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
