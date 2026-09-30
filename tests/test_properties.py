"""Property tests: random months of group activity, with a faulty feed, must
always end with the books agreeing with the bank to the cent."""
import os
from decimal import Decimal

from django.db import connection
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from connectivity.models import Alert, LineResolution, StatementLine
from governance.models import Mandate
from simulator import bank
from simulator.bank import Faults, SimulatorConnector
from simulator.models import SimAccount

from .factories import approve_withdrawal, make_group
from .helpers import assert_sound, sync

N = "0012345678901"
EXAMPLES = int(os.environ.get("WEPL_PROPERTY_EXAMPLES", "40"))

cents = st.integers(min_value=100, max_value=5_000_000).map(lambda c: Decimal(c) / 100)
event = st.one_of(
    st.tuples(st.just("deposit"), st.integers(0, 5), cents),          # 5 = unknown payer
    st.tuples(st.just("approved_out"), st.booleans(), cents),         # quote the reference or not
    st.tuples(st.just("unapproved_out"), st.just(None), cents),
    st.tuples(st.just("interest"), st.just(None), cents.map(lambda c: (c / 100).quantize(Decimal("0.01")) or Decimal("0.01"))),
    st.tuples(st.just("charge"), st.just(None), st.integers(1, 20000).map(lambda c: Decimal(c) / 100)),
    st.tuples(st.just("sync"), st.integers(0, 999), st.just(None)),
)


class LedgerMatchesBankProperty(TestCase):
    @settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(st.lists(event, min_size=1, max_size=25))
    def test_any_history_reconciles(self, events):
        group, fund, members, ea = make_group()
        expected_matched = 0
        for kind, arg, amount in events:
            balance = SimAccount.objects.get(number=N).balance
            if kind == "deposit":
                msisdn = members[arg].person.msisdn if arg < 5 else "254700999000"
                bank.deposit(N, amount, msisdn=msisdn, name="PAYER")
            elif kind == "approved_out" and amount <= balance:
                mandate = approve_withdrawal(members, fund, amount, payee_account="0799000000")
                narration = f"PAY {mandate.reference}" if arg else "PAY"
                bank.withdraw(N, amount, narration=narration, payee_msisdn="254799000000" if not arg else "")
                expected_matched += 1 if arg else 0
            elif kind == "unapproved_out" and amount <= balance:
                bank.withdraw(N, amount, narration="CASH WITHDRAWAL")
            elif kind == "interest":
                bank.credit_interest(N, amount)
            elif kind == "charge" and amount <= balance:
                bank.charge(N, amount)
            elif kind == "sync":
                sync(ea, SimulatorConnector(Faults(duplicate_rate=0.3, withhold_rate=0.3, reorder=True, seed=arg)))

        _, run = sync(ea)  # the end-of-day sweep always completes the picture
        self.assertTrue(run.balanced, run.__dict__)
        self.assertEqual(run.difference or 0, 0)
        self.assertEqual(run.statement_balance or 0, SimAccount.objects.get(number=N).balance)
        self.assertEqual(run.lines_unresolved, 0)
        assert_sound(self, ea)
        matched = LineResolution.objects.filter(outcome="matched", line__external_account=ea).count()
        self.assertGreaterEqual(matched, expected_matched)
        # Every mandate is used at most once, and every executed one points at a real line.
        for m in Mandate.objects.filter(status=Mandate.Status.EXECUTED):
            self.assertTrue(StatementLine.objects.filter(pk=m.executed_by_line_id).exists())
        unapproved = StatementLine.objects.filter(kind="withdrawal").count() - matched
        self.assertEqual(Alert.objects.filter(kind="unmatched_outflow").count(), unapproved)
        with connection.cursor() as c:  # fire the deferred balance triggers now
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
