"""Property tests: random histories of group activity over a faulty feed must
always end with the books agreeing with the bank to the cent."""
import os
from decimal import Decimal

from django.db import connection
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from contexts.custody.public import open_alerts, statement_lines
from contexts.governance.infrastructure.models import Mandate
from simulators.im_bank import bank
from simulators.im_bank.connector import Faults, SimulatorConnector
from tests.scenario import Scenario

N = "0012345678901"
EXAMPLES = int(os.environ.get("WEPL_PROPERTY_EXAMPLES", "40"))

cents = st.integers(min_value=100, max_value=5_000_000).map(lambda c: Decimal(c) / 100)
event = st.one_of(
    st.tuples(st.just("deposit"), st.integers(0, 5), cents),          # 5 = a payer who is not a member
    st.tuples(st.just("approved_out"), st.booleans(), cents),         # quoting the reference or not
    st.tuples(st.just("unapproved_out"), st.just(None), cents),
    st.tuples(st.just("interest"), st.just(None), st.integers(1, 50000).map(lambda c: Decimal(c) / 100)),
    st.tuples(st.just("charge"), st.just(None), st.integers(1, 20000).map(lambda c: Decimal(c) / 100)),
    st.tuples(st.just("sync"), st.integers(0, 999), st.just(None)),
)


class BooksMatchBankProperty(TestCase):
    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(st.lists(event, min_size=1, max_size=25))
    def test_any_history_reconciles(self, events):
        s = Scenario()
        with s.acting():  # each example is its own tenant
            self.run_history(s, events)
        with connection.cursor() as c:  # fire the deferred balance triggers now, outside any tenant
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
            c.execute("SET CONSTRAINTS ALL DEFERRED")

    def run_history(self, s, events):
        for kind, arg, amount in events:
            available = bank.balance(N).amount
            if kind == "deposit":
                bank.deposit(N, amount, msisdn=s.m[arg].msisdn if arg < 5 else "254700999000", name="PAYER")
            elif kind == "approved_out" and amount <= available:
                ref = s.approve(amount)
                bank.withdraw(N, amount, narration=f"PAY {ref}" if arg else "PAY",
                              payee_msisdn="" if arg else "254799000000")
            elif kind == "unapproved_out" and amount <= available:
                bank.withdraw(N, amount, narration="CASH WITHDRAWAL")
            elif kind == "interest":
                bank.credit_interest(N, amount)
            elif kind == "charge" and amount <= available:
                bank.charge(N, amount)
            elif kind == "sync":
                s.sync(SimulatorConnector(Faults(duplicate_rate=0.3, withhold_rate=0.3, reorder=True, seed=arg)))

        _, run = s.sync()  # the end-of-day sweep always completes the picture
        self.assertTrue(run.balanced, run)
        self.assertEqual(run.statement_balance or 0, bank.balance(N).amount)
        self.assertEqual(run.lines_unresolved, 0)
        s.assert_sound(self)
        lines = statement_lines(s.ea.id)
        payouts = [l for l in lines if l["kind"] == "withdrawal"]
        matched = [l for l in payouts if l["outcome"] == "matched"]
        self.assertEqual(len(open_alerts(s.group.id, kind="unmatched_outflow")), len(payouts) - len(matched))
        executed = Mandate.objects.filter(status="executed")
        self.assertEqual(executed.count(), len(matched))
        self.assertEqual({m.executed_by_line_id for m in executed}, {l["id"] for l in matched})
