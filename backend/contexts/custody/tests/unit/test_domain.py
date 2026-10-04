from datetime import datetime, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from contexts.custody.domain import accounting
from contexts.custody.domain.accounting import AccountingError, FundBook
from contexts.custody.domain.attribution import MemberFacts, attribute
from contexts.custody.domain.matching import match_outflow, quoted_references
from contexts.custody.domain.reconciliation import assess, balance_breaks
from contexts.custody.domain.resolution import InvalidCorrection, Outcome, ensure_correction
from contexts.governance.contract import Allocation, MandateStatus, MandateView, SharingRule
from contexts.ledger.contract import AccountPurpose, Side
from contexts.shared_kernel.money import Money

MEMBERS = [MemberFacts(1, "M01", "254712000001"), MemberFacts(2, "M02", "254712000002")]
BOOK = FundBook(group_id=1, fund_id=1, external_account_id=9)


def mandate(mid=1, amount="1000", status=MandateStatus.ISSUED, ref="WMABCDEF", payee="0799000000"):
    return MandateView(id=mid, group_id=1, fund_id=1, reference=ref, amount=Money(amount), payee_name="S",
                       payee_account=payee, allocation=Allocation.PRO_RATA, charged_member_id=None, status=status,
                       expires_at=datetime.now(timezone.utc))


class AttributionTests(SimpleTestCase):
    def attr(self, **kw):
        base = dict(reference="", narration="", payer_msisdn="", members=MEMBERS, remembered_payers={})
        return attribute(**{**base, **kw})

    def test_member_code_wins(self):
        self.assertEqual(self.attr(reference="ACC M02", payer_msisdn="0712000001"), 2)

    def test_remembered_payer_then_own_number(self):
        self.assertEqual(self.attr(payer_msisdn="0733000000", remembered_payers={"254733000000": 1}), 1)
        self.assertEqual(self.attr(payer_msisdn="+254712000002"), 2)

    def test_an_ended_spells_code_always_means_that_spell(self):
        """John was M01, left, and is M03 now. A payment quoting M01 is held for
        a person to decide; it is never moved to M03 or credited to M01."""
        ended = [MemberFacts(1, "M01", "254712000001", active=False), MemberFacts(3, "M03", "254712000001")]
        self.assertIsNone(self.attr(members=ended, reference="M01", payer_msisdn="0712000001"))
        self.assertEqual(self.attr(members=ended, payer_msisdn="0712000001"), 3)
        self.assertIsNone(self.attr(members=ended[:1], payer_msisdn="0712000001"))

    def test_unknown_or_departed_payer_is_not_guessed(self):
        self.assertIsNone(self.attr(payer_msisdn="0733000000"))
        self.assertIsNone(self.attr(payer_msisdn="0733000000", remembered_payers={"254733000000": 99}))
        self.assertIsNone(self.attr(payer_msisdn="garbage"))


class MatchingTests(SimpleTestCase):
    def test_quoted_reference_must_be_issued_and_exact(self):
        m = mandate()
        self.assertEqual(quoted_references("PESALINK WMABCDEF", ""), ["WMABCDEF"])
        ok = match_outflow(amount=Money("1000"), payee_msisdn="", quoted=["WMABCDEF"], referenced=m, candidates=[])
        self.assertEqual(ok.mandate_id, 1)
        for referenced, amount, words in ((None, "1000", "not a mandate"), (m, "1200", "is for"),
                                          (mandate(status=MandateStatus.EXPIRED), "1000", "expired")):
            r = match_outflow(amount=Money(amount), payee_msisdn="", quoted=["WMABCDEF"], referenced=referenced,
                              candidates=[])
            self.assertIsNone(r.mandate_id)
            self.assertIn(words, r.reason)

    def test_without_reference_only_an_unambiguous_candidate_matches(self):
        one = match_outflow(amount=Money("1000"), payee_msisdn="254799000000", quoted=[], referenced=None,
                            candidates=[mandate(1), mandate(2, payee="0799111111")])
        self.assertEqual(one.mandate_id, 1)
        two = match_outflow(amount=Money("1000"), payee_msisdn="", quoted=[], referenced=None,
                            candidates=[mandate(1), mandate(2)])
        self.assertIsNone(two.mandate_id)
        self.assertIn("Several", two.reason)
        none = match_outflow(amount=Money("1000"), payee_msisdn="", quoted=[], referenced=None, candidates=[])
        self.assertIn("No approved mandate", none.reason)


class AccountingTests(SimpleTestCase):
    def purposes(self, draft):
        return {(p.account.purpose, p.account.member_id, p.side): p.amount for p in draft.postings}

    def test_receipt_to_member_or_suspense(self):
        d = accounting.receipt(BOOK, key="k", line_id=1, amount=Money("100"), member_id=2)
        self.assertEqual(self.purposes(d)[(AccountPurpose.MEMBER_INTEREST, 2, Side.CREDIT)], Money("100"))
        d = accounting.receipt(BOOK, key="k", line_id=1, amount=Money("100"), member_id=None)
        self.assertIn((AccountPurpose.UNATTRIBUTED_IN, None, Side.CREDIT), self.purposes(d))

    def test_interest_pro_rata_or_retained(self):
        d = accounting.interest(BOOK, key="k", line_id=1, amount=Money("40"), rule=SharingRule.PRO_RATA,
                                member_ids=[1, 2], balances={1: Money("3000"), 2: Money("1000")})
        self.assertEqual(self.purposes(d)[(AccountPurpose.MEMBER_INTEREST, 1, Side.CREDIT)], Money("30"))
        d = accounting.interest(BOOK, key="k", line_id=1, amount=Money("40"), rule=SharingRule.RETAINED,
                                member_ids=[1, 2], balances={})
        self.assertIn((AccountPurpose.RETAINED, None, Side.CREDIT), self.purposes(d))

    def test_payout_charged_to_one_member(self):
        d = accounting.authorised_payout(BOOK, key="k", line_id=1, amount=Money("500"), allocation=Allocation.MEMBER,
                                         charged_member_id=2, member_ids=[1, 2], balances={}, reference="WM")
        self.assertEqual(self.purposes(d)[(AccountPurpose.MEMBER_INTEREST, 2, Side.DEBIT)], Money("500"))

    def test_opening_balances_cannot_exceed_the_bank(self):
        with self.assertRaises(AccountingError):
            accounting.opening_balances(BOOK, key="k", line_id=1, statement_balance=Money("100"),
                                        signed_off={1: Money("200")})
        d = accounting.opening_balances(BOOK, key="k", line_id=1, statement_balance=Money("100"),
                                        signed_off={1: Money("60")})
        self.assertEqual(self.purposes(d)[(AccountPurpose.UNATTRIBUTED_IN, None, Side.CREDIT)], Money("40"))

    def test_sharing_needs_members(self):
        with self.assertRaises(AccountingError):
            accounting.share_pro_rata(Money("1"), [], {})


class ReconciliationAndCorrectionTests(SimpleTestCase):
    def test_assessment(self):
        ok = assess(statement_balance=Money("10"), ledger_cash=Money("10"), sequences=[1, 2, 3], unresolved=0)
        self.assertTrue(ok.balanced)
        gap = assess(statement_balance=Money("10"), ledger_cash=Money("10"), sequences=[1, 3], unresolved=0)
        self.assertEqual(gap.gaps, (2,))
        self.assertFalse(gap.balanced)
        diff = assess(statement_balance=Money("10"), ledger_cash=Money("7"), sequences=[1], unresolved=0)
        self.assertEqual(diff.difference, Money("-3"))
        self.assertFalse(assess(statement_balance=None, ledger_cash=Money("0"), sequences=[1], unresolved=1).balanced)
        broken = assess(statement_balance=Money("10"), ledger_cash=Money("10"), sequences=[1, 2], unresolved=0,
                        breaks=(2,))
        self.assertFalse(broken.balanced)

    def test_running_balance_chain(self):
        D = Decimal
        chain = [(0, "opening", D("100"), D("100")), (1, "deposit", D("50"), D("150")),
                 (2, "withdrawal", D("30"), D("120")), (3, "charge", D("5"), D("115")),
                 (4, "interest", D("1"), D("116"))]
        self.assertEqual(balance_breaks(chain), ())
        without_line_2 = [chain[0], chain[1], chain[3], chain[4]]
        self.assertEqual(balance_breaks(without_line_2), (3,))  # reported once, where it shows
        unknown = [chain[0], (1, "deposit", D("50"), None), chain[2]]
        self.assertEqual(balance_breaks(unknown), ())  # carried to the next printed balance
        self.assertEqual(balance_breaks([(1, "deposit", D("50"), D("80"))]), (1,))  # an account starts at zero
        self.assertEqual(balance_breaks([]), ())

    def test_only_listed_corrections_are_allowed(self):
        ensure_correction(Outcome.UNATTRIBUTED, Outcome.ATTRIBUTED)
        ensure_correction(Outcome.UNMATCHED, Outcome.EXPLAINED)
        for current, new in ((Outcome.ATTRIBUTED, Outcome.ATTRIBUTED), (Outcome.MATCHED, Outcome.EXPLAINED),
                             (None, Outcome.ATTRIBUTED)):
            with self.assertRaises(InvalidCorrection):
                ensure_correction(current, new)
