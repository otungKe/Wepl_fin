from django.test import SimpleTestCase

from contexts.ledger.contract import AccountKey, AccountKeyError, AccountPurpose, JournalDraft, LedgerError, Posting, Side
from contexts.shared_kernel.money import Money

CASH = AccountKey(1, 1, AccountPurpose.CUSTODY_CASH, external_account_id=9)
MEMBER = AccountKey(1, 1, AccountPurpose.MEMBER_INTEREST, member_id=5)
D, C = Side.DEBIT, Side.CREDIT


def draft(*postings, key="k", **kw):
    return JournalDraft(idempotency_key=key, group_id=1, fund_id=1, kind="t", cause_type="t", cause_id="1",
                        postings=postings, **kw)


class AccountKeyTests(SimpleTestCase):
    def test_member_interest_needs_a_member_and_cash_an_external_account(self):
        with self.assertRaises(AccountKeyError):
            AccountKey(1, 1, AccountPurpose.MEMBER_INTEREST)
        with self.assertRaises(AccountKeyError):
            AccountKey(1, 1, AccountPurpose.CUSTODY_CASH)
        with self.assertRaises(AccountKeyError):
            AccountKey(1, 1, AccountPurpose.RETAINED, member_id=3)

    def test_normal_sides(self):
        self.assertEqual(AccountPurpose.CUSTODY_CASH.normal_side, D)
        self.assertEqual(AccountPurpose.UNEXPLAINED_OUT.normal_side, D)
        self.assertEqual(AccountPurpose.MEMBER_INTEREST.normal_side, C)


class JournalDraftTests(SimpleTestCase):
    def test_a_balanced_entry_is_valid(self):
        d = draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        self.assertEqual(len(d.postings), 2)

    def test_unbalanced_single_line_zero_and_negative_entries_are_refused(self):
        with self.assertRaisesMessage(LedgerError, "does not balance"):
            draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("9")))
        with self.assertRaisesMessage(LedgerError, "at least two"):
            draft(Posting(CASH, D, Money("10")))
        for bad in ("0", "-1"):
            with self.assertRaisesMessage(LedgerError, "positive"):
                Posting(CASH, D, Money(bad))

    def test_postings_must_stay_in_the_entry_fund_and_currency(self):
        other_fund = AccountKey(1, 2, AccountPurpose.RETAINED)
        with self.assertRaisesMessage(LedgerError, "group and fund"):
            draft(Posting(CASH, D, Money("1")), Posting(other_fund, C, Money("1")))
        with self.assertRaisesMessage(LedgerError, "currency"):
            Posting(CASH, D, Money("1", "USD"))

    def test_build_merges_and_drops_zeroes(self):
        d = JournalDraft.build(idempotency_key="k", group_id=1, fund_id=1, kind="t", cause_type="t", cause_id=1,
                               postings=[(CASH, D, Money("4")), (CASH, D, Money("6")), (MEMBER, C, Money("10")),
                                         (MEMBER, C, Money("0"))])
        self.assertEqual(len(d.postings), 2)

    def test_reversal_mirrors_every_posting(self):
        d = draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        r = d.reversal(entry_id=7, idempotency_key="r")
        self.assertEqual({(p.account, p.side) for p in r.postings}, {(CASH, C), (MEMBER, D)})
        self.assertEqual(r.reverses_entry_id, 7)

    def test_a_reversal_names_the_entry_it_reverses_as_its_cause(self):
        """The cause is fingerprinted, so this puts the reversed entry in the
        reversal's idempotency identity."""
        d = draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        r = d.reversal(entry_id=7, idempotency_key="r")
        self.assertEqual((r.cause_type, r.cause_id), ("journal_entry", "7"))
        self.assertNotEqual(r.fingerprint(), d.reversal(entry_id=8, idempotency_key="r").fingerprint())
        from dataclasses import replace
        with self.assertRaisesMessage(LedgerError, "cause must be the entry it reverses"):
            replace(r, cause_id="8")
        with self.assertRaisesMessage(LedgerError, "cause must be the entry it reverses"):
            replace(r, cause_type="t")

    def test_fingerprint_ignores_order_but_not_content(self):
        a = draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        b = draft(Posting(MEMBER, C, Money("10")), Posting(CASH, D, Money("10")))
        c = draft(Posting(CASH, D, Money("11")), Posting(MEMBER, C, Money("11")))
        self.assertEqual(a.fingerprint(), b.fingerprint())
        self.assertNotEqual(a.fingerprint(), c.fingerprint())

    def test_every_entry_names_its_kind_and_cause(self):
        """Traceability: an entry always says what it is and what caused it.
        A missing cause id is refused, not stored as the text "None"."""
        p = (Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        for field, value in (("kind", ""), ("cause_type", ""), ("cause_id", ""), ("cause_id", None)):
            fields = {**dict(idempotency_key="k", group_id=1, fund_id=1, kind="t", cause_type="t", cause_id="1",
                             postings=p), field: value}
            with self.subTest(field=field, value=value), self.assertRaisesMessage(LedgerError, "kind and a cause"):
                JournalDraft(**fields)
        self.assertEqual(draft(*p).cause_id, "1")

    def test_the_fingerprint_is_pinned(self):
        """Stored fingerprints must keep matching honest replays. The text
        includes AccountKey's repr, and so the enum's: if a Python upgrade or
        a change to AccountKey alters it, every replay of an older entry would
        be refused as key reuse. If this fails, stored fingerprints need a
        migration first (see JournalDraft.fingerprint)."""
        d = draft(Posting(CASH, D, Money("10")), Posting(MEMBER, C, Money("10")))
        self.assertEqual(d.fingerprint(), "\n".join([
            "t", "t", "1",
            "AccountKey(group_id=1, fund_id=1, purpose=<AccountPurpose.CUSTODY_CASH: 'custody_cash'>, member_id=None, "
            "external_account_id=9, currency='KES')|D|10.00|KES",
            "AccountKey(group_id=1, fund_id=1, purpose=<AccountPurpose.MEMBER_INTEREST: 'member_interest'>, "
            "member_id=5, external_account_id=None, currency='KES')|C|10.00|KES"]))
