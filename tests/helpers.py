from decimal import Decimal

from connectivity import services as conn
from connectivity.models import Alert, StatementLine
from ledger import services as ledger
from ledger.models import Account
from simulator.bank import SimulatorConnector

P = Account.Purpose


def sync(ea, connector=None):
    return conn.sync(ea, connector or SimulatorConnector(sweep=True))


def assert_sound(tc, ea):
    """The invariants I&M is asked to rely on."""
    pos = ledger.fund_position(ea.fund_id)
    tc.assertEqual(ledger.trial_balance(ea.fund_id), 0)
    tc.assertEqual(pos[P.CUSTODY_CASH],
                   pos[P.MEMBER_INTEREST] + pos[P.UNATTRIBUTED_IN] + pos[P.RETAINED] - pos[P.UNEXPLAINED_OUT])
    # Every outflow is either matched to a mandate or has an alert.
    for line in StatementLine.objects.filter(external_account=ea, kind=StatementLine.Kind.WITHDRAWAL):
        latest = line.resolutions.order_by("-id").first()
        tc.assertIsNotNone(latest, f"line {line.bank_txn_id} was never processed")
        if latest.outcome in ("matched", "explained"):
            tc.assertIsNotNone(latest.mandate_id)
        else:
            tc.assertTrue(Alert.objects.filter(line=line, kind=Alert.Kind.UNMATCHED_OUTFLOW).exists())
    return pos


def member_balance(ea, membership) -> Decimal:
    return ledger.balances(ea.fund_id, P.MEMBER_INTEREST).get(membership.pk, Decimal("0.00"))
