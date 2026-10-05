from datetime import date

from django.test import SimpleTestCase

from contexts.contributions.domain.schedule import due_dates, owed_from, periods
from contexts.contributions.domain.standing import standing
from contexts.governance.contract import (ContributionRule, ExtraPayments, FineKind, JoinersOweFrom, LateFine,
                                          PaymentOrder, RulesError)
from contexts.governance.contract import ConstitutionRules
from contexts.shared_kernel.money import Money

RAW = {"fund_id": 1, "frequency": "monthly", "amount": "1000", "due_day": 5, "starts_on": "2026-07-01",
       "payment_order": "oldest_first", "joiners_owe_from": "joining", "extra_payments": "pay_ahead",
       "late_fine": {"kind": "fixed", "value": "50", "grace_days": 3}, "leaver_arrears": "written_off"}
RULE = ContributionRule.parse(RAW)
NO_FINE = LateFine(FineKind.NONE)
K = Money


def d(month, day):
    return date(2026, month, day)


class RuleTests(SimpleTestCase):
    def test_round_trips_and_refuses_what_the_group_did_not_state(self):
        self.assertEqual(ContributionRule.parse(RULE.to_dict()), RULE)
        for name in ("frequency", "amount", "payment_order", "extra_payments", "late_fine", "leaver_arrears"):
            with self.subTest(name), self.assertRaises(ValueError):
                ContributionRule.parse({k: v for k, v in RAW.items() if k != name})
        for bad in ({"due_day": 29}, {"amount": "0"}, {"late_fine": {"kind": "percent", "value": "150",
                                                                     "grace_days": 1}}):
            with self.subTest(bad), self.assertRaises(ValueError):
                ContributionRule.parse({**RAW, **bad})

    def test_a_fund_has_at_most_one_rule_in_a_constitution(self):
        base = {"approvals": [{"up_to": None, "approvers": "members", "required": 1}]}
        self.assertEqual(ConstitutionRules.parse({**base, "contributions": [RAW]}).contribution_rule(1), RULE)
        with self.assertRaises(RulesError):
            ConstitutionRules.parse({**base, "contributions": [RAW, RAW]})


class ScheduleTests(SimpleTestCase):
    def test_monthly_and_weekly_due_dates(self):
        self.assertEqual(due_dates(RULE, d(6, 1), d(9, 4)), [d(7, 5), d(8, 5)])
        weekly = ContributionRule.parse({**RAW, "frequency": "weekly", "due_day": 3})  # Wednesdays
        self.assertEqual(due_dates(weekly, d(7, 1), d(7, 20)), [d(7, 1), d(7, 8), d(7, 15)])

    def test_joiners_owe_from_joining_or_from_the_start_as_the_group_chose(self):
        self.assertEqual(owed_from(RULE, d(8, 10)), d(8, 10))
        start = ContributionRule.parse({**RAW, "joiners_owe_from": "start"})
        self.assertEqual(owed_from(start, d(8, 10)), d(7, 1))

    def test_each_period_takes_the_rule_in_force_on_its_due_date(self):
        dearer = ContributionRule.parse({**RAW, "amount": "1500"})
        got = periods([(d(6, 1), RULE), (d(8, 20), dearer)], joined_on=d(6, 1), until=d(9, 30), upcoming=True)
        self.assertEqual(got, [(d(7, 5), K("1000")), (d(8, 5), K("1000")), (d(9, 5), K("1500")),
                               (d(10, 5), K("1500"))])
        self.assertEqual(periods([(d(6, 1), RULE), (d(8, 20), None)], joined_on=d(6, 1), until=d(9, 30),
                                 upcoming=True), [(d(7, 5), K("1000")), (d(8, 5), K("1000"))])


DUE = [(d(7, 5), K("1000")), (d(8, 5), K("1000")), (d(9, 5), K("1000")), (d(10, 5), K("1000"))]


def run(payments, *, as_of=d(9, 20), order=PaymentOrder.OLDEST_FIRST, extra=ExtraPayments.PAY_AHEAD, fine=NO_FINE,
        write_off=False):
    return standing(DUE, [(on, K(a)) for on, a in payments], as_of=as_of, order=order, extra=extra, fine=fine,
                    write_off=write_off)


class StandingTests(SimpleTestCase):
    def test_arrears_are_what_was_due_less_what_cleared_it(self):
        s = run([(d(7, 2), "1000"), (d(8, 20), "500")])
        self.assertEqual((s.due, s.paid, s.arrears), (K("3000"), K("1500"), K("1500")))
        self.assertEqual(s.overdue, ((d(8, 5), K("500")), (d(9, 5), K("1000"))))

    def test_paying_more_is_paying_ahead_or_savings_as_the_group_chose(self):
        ahead = run([(d(7, 2), "4500")])
        self.assertEqual((ahead.arrears, ahead.paid_ahead), (K("0"), K("1500")))
        savings = run([(d(7, 2), "4500")], extra=ExtraPayments.SAVINGS)
        self.assertEqual((savings.arrears, savings.paid_ahead), (K("2000"), K("0")))

    def test_a_payment_counts_for_the_period_running_up_to_its_due_date(self):
        s = run([(d(7, 1), "1000"), (d(8, 1), "1000"), (d(9, 1), "1000"), (d(9, 18), "1000")],
                extra=ExtraPayments.SAVINGS)
        self.assertEqual((s.arrears, s.paid_ahead), (K("0"), K("1000")))  # 18 Sep is towards 5 Oct

    def test_payment_order_decides_which_period_is_cleared(self):
        late = [(d(9, 10), "1000")]
        self.assertEqual(run(late).overdue[0][0], d(8, 5))
        self.assertEqual(run(late, order=PaymentOrder.CURRENT_FIRST).overdue[0][0], d(7, 5))

    def test_a_late_period_is_fined_once_on_what_was_owed_when_grace_ran_out(self):
        fixed = LateFine(FineKind.FIXED, K("50").amount, 3)
        s = run([(d(7, 7), "1000"), (d(8, 20), "1000")], fine=fixed)
        self.assertEqual(s.fines, ((d(8, 5), K("50")), (d(9, 5), K("50"))))  # 7 Jul is within grace
        pct = run([(d(8, 20), "600")], fine=LateFine(FineKind.PERCENT, K("10").amount, 3))
        self.assertEqual(pct.fines, ((d(7, 5), K("100")), (d(8, 5), K("100")), (d(9, 5), K("100"))))
        self.assertEqual(run([], as_of=d(9, 7), fine=fixed).fines, ((d(7, 5), K("50")), (d(8, 5), K("50"))))

    def test_a_leavers_arrears_are_written_off_when_the_group_says_so(self):
        s = run([], fine=LateFine(FineKind.FIXED, K("50").amount, 0), write_off=True)
        self.assertEqual((s.arrears, s.fines, s.written_off), (K("0"), (), K("3150")))
