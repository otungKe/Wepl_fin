"""The ledger's rules hold in PostgreSQL too, whatever code writes to it."""
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, LedgerError, Posting, Side
from contexts.ledger.infrastructure.models import Account, JournalEntry, JournalLine
from contexts.ledger.public import (account_balance, fund_position, member_balances, post_journal, reverse_journal,
                                    trial_balance)
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import cross_tenant, tenant

D, C = Side.DEBIT, Side.CREDIT


class RealBooks:
    """A group with a fund, a member and a custodian account, acted for until
    the test ends. Ledger rows name real ones (ADR-0017)."""

    def setUp(self):
        from contexts.communities.public import add_member, create_group, open_fund
        from contexts.custody.public import link_external_account
        group = create_group("Ledger tests", actor="test")
        self.enterContext(tenant(group.tenant_id))
        fund = open_fund(group.id, name="Main savings", actor="test")
        self.group_id, self.fund_id = group.id, fund.id
        self.member_id = add_member(group.id, msisdn="0700000005", name="Member", actor="test").id
        ea = link_external_account(fund.id, institution="Custodian Bank", account_number=f"L{fund.id}",
                                   account_name="Ledger tests", connector="upload", actor="test")
        self.cash = AccountKey(group.id, fund.id, AccountPurpose.CUSTODY_CASH, external_account_id=ea.id)
        self.member = AccountKey(group.id, fund.id, AccountPurpose.MEMBER_INTEREST, member_id=self.member_id)

    def draft(self, key="k", amount="100"):
        return JournalDraft(idempotency_key=key, group_id=self.group_id, fund_id=self.fund_id, kind="t",
                            cause_type="t", cause_id="1", postings=(Posting(self.cash, D, Money(amount)),
                                                                    Posting(self.member, C, Money(amount))))


def check_deferred():
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("SET CONSTRAINTS ALL DEFERRED")


class PostingTests(RealBooks, TestCase):

    def test_balances_are_derived_by_normal_side(self):
        post_journal(self.draft())
        self.assertEqual(account_balance(self.cash), Money("100"))
        self.assertEqual(member_balances(self.fund_id), {self.member_id: Money("100")})
        self.assertTrue(fund_position(self.fund_id).invariant_holds)
        self.assertEqual(trial_balance(self.fund_id), 0)

    def test_distinct_keys_accumulate_and_a_replay_changes_nothing(self):
        """An idempotency test must tell "same key again" from "two keys"."""
        first = post_journal(self.draft("a"))
        post_journal(self.draft("b"))
        self.assertEqual(account_balance(self.cash), Money("200"))
        self.assertEqual(post_journal(self.draft("a")), first)
        self.assertEqual(account_balance(self.cash), Money("200"))

    def test_same_key_different_entry_is_refused(self):
        post_journal(self.draft("same", "100"))
        with self.assertRaisesMessage(LedgerError, "different entry"):
            post_journal(self.draft("same", "101"))

    def test_one_account_per_key_even_with_null_parts(self):
        from contexts.ledger.infrastructure.accounts import resolve
        retained = AccountKey(self.group_id, self.fund_id, AccountPurpose.RETAINED)
        self.assertEqual(resolve(retained).pk, resolve(retained).pk)
        self.assertEqual(resolve(self.member).pk, resolve(self.member).pk)

    def test_reversal_restores_balances_once(self):
        entry = post_journal(self.draft("r"))
        reverse_journal(entry, idempotency_key="r:rev")
        reverse_journal(entry, idempotency_key="r:rev")
        with self.assertRaisesMessage(LedgerError, "already been reversed"):
            reverse_journal(entry, idempotency_key="r:rev2")
        self.assertEqual(account_balance(self.cash), Money("0"))
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_a_reversal_is_itself_reversible_once(self):
        """Harry's rule (2026-10-01, ADR-0003): a reversal is an immutable entry
        like any other, so a wrong reversal is corrected by reversing it, never
        by an edit or a special case. Each entry is reversed at most once."""
        original = post_journal(self.draft("o"))
        reversal = reverse_journal(original, idempotency_key="o:rev")
        self.assertEqual(account_balance(self.cash), Money("0"))
        restored = reverse_journal(reversal, idempotency_key="o:rev:rev")
        self.assertEqual(account_balance(self.cash), Money("100"))
        self.assertEqual(JournalEntry.objects.get(pk=restored).reverses_id, reversal)
        with self.assertRaisesMessage(LedgerError, "already been reversed"):
            reverse_journal(reversal, idempotency_key="o:rev:rev-again")
        reverse_journal(restored, idempotency_key="o:rev:rev:rev")
        self.assertEqual(account_balance(self.cash), Money("0"))
        self.assertEqual(JournalEntry.objects.count(), 4)
        self.assertEqual(trial_balance(self.fund_id), 0)

    def test_a_reversal_retry_returns_the_same_entry(self):
        entry = post_journal(self.draft("r"))
        first = reverse_journal(entry, idempotency_key="r:rev", memo="first")
        self.assertEqual(reverse_journal(entry, idempotency_key="r:rev", memo="retried"), first)

    def test_a_reversal_key_cannot_be_reused_for_another_entry(self):
        """The reversed entry is part of a reversal's identity: the same key
        reversing a different, identical-looking entry is not a replay."""
        one, two = post_journal(self.draft("one")), post_journal(self.draft("two"))
        reverse_journal(one, idempotency_key="undo")
        with self.assertRaisesMessage(LedgerError, "different entry"):
            reverse_journal(two, idempotency_key="undo")
        self.assertFalse(JournalEntry.objects.filter(reverses_id=two).exists())

    def test_reversing_an_unknown_entry_is_a_ledger_error(self):
        with self.assertRaisesMessage(LedgerError, "Unknown journal entry"):
            reverse_journal(999_999, idempotency_key="ghost")
        self.assertEqual(JournalEntry.objects.count(), 0)
        from contexts.ledger.public import entry_fund
        with self.assertRaisesMessage(LedgerError, "Unknown journal entry"):
            entry_fund(999_999)  # was JournalEntry.DoesNotExist, an internal type

    def test_load_draft_round_trips_what_was_posted(self):
        from contexts.ledger.application.posting import load_draft
        entry = post_journal(self.draft("rt"))
        reversal = reverse_journal(entry, idempotency_key="rt:rev")
        for entry_id in (entry, reversal):
            stored = JournalEntry.objects.get(pk=entry_id)
            loaded = load_draft(entry_id)
            self.assertEqual(loaded.fingerprint(), stored.fingerprint)
            self.assertEqual((loaded.idempotency_key, loaded.kind, loaded.cause_type, loaded.cause_id, loaded.memo),
                             (stored.idempotency_key, stored.kind, stored.cause_type, stored.cause_id, stored.memo))
            self.assertEqual([p.account.purpose.value for p in loaded.postings],
                             list(stored.lines.order_by("id").values_list("account__purpose", flat=True)))
        self.assertIsNone(load_draft(entry).reverses_entry_id)
        self.assertEqual(load_draft(reversal).reverses_entry_id, entry)

    def test_an_unrelated_integrity_error_is_not_read_as_a_reversal_race(self):
        """Only the reversal constraint means "already reversed". Here the
        entry is already reversed, and an unrelated failure must still
        surface as itself."""
        from unittest import mock
        from django.db import IntegrityError
        from contexts.ledger.application.posting import load_draft
        entry = post_journal(self.draft("u"))
        reverse_journal(entry, idempotency_key="u:rev")
        again = load_draft(entry).reversal(entry_id=entry, idempotency_key="u:rev2")
        with mock.patch.object(JournalEntry.objects, "create", side_effect=IntegrityError("unrelated")):
            with self.assertRaisesMessage(IntegrityError, "unrelated"):
                post_journal(again)
        with mock.patch.object(JournalEntry.objects, "create", side_effect=IntegrityError("unrelated")):
            with self.assertRaisesMessage(IntegrityError, "unrelated"):
                post_journal(self.draft("fresh"))  # nor as a replay

    def test_movements_run_in_posting_order_with_a_running_balance(self):
        from contexts.ledger.public import member_movements
        post_journal(self.draft("m1", "100"))
        out = JournalDraft(idempotency_key="m2", group_id=self.group_id, fund_id=self.fund_id, kind="t", cause_type="t", cause_id="2",
                           postings=(Posting(self.member, D, Money("30")), Posting(self.cash, C, Money("30"))))
        post_journal(out)
        post_journal(self.draft("m3", "5"))
        rows = member_movements(self.fund_id, self.member_id)
        self.assertEqual([(r["in"], r["out"], r["balance"]) for r in rows],
                         [(Money("100").amount, None, Money("100").amount), (None, Money("30").amount,
                          Money("70").amount), (Money("5").amount, None, Money("75").amount)])
        self.assertEqual(rows[-1]["balance"], member_balances(self.fund_id)[self.member_id].amount)
        self.assertEqual(trial_balance(self.fund_id), 0)
        self.assertTrue(fund_position(self.fund_id).invariant_holds)

    def test_a_members_movements_and_the_trial_balance_stay_in_one_currency(self):
        """Should a second currency ever reach a fund's books (today only a
        restore could put one there: communities 0020), no query may add
        amounts across currencies."""
        from contexts.ledger.tests.integration.test_database_rules import accounts_in_any_currency
        post_journal(self.draft("kes", "100"))
        usd = lambda p, **kw: AccountKey(self.group_id, self.fund_id, p, currency="USD", **kw)
        with accounts_in_any_currency():
            post_journal(JournalDraft(idempotency_key="usd", group_id=self.group_id, fund_id=self.fund_id, kind="t",
                                      cause_type="t", cause_id="usd", postings=(
                                          Posting(usd(AccountPurpose.UNEXPLAINED_OUT), D, Money("7", "USD")),
                                          Posting(usd(AccountPurpose.MEMBER_INTEREST, member_id=self.member_id), C,
                                                  Money("7", "USD")))))
        from contexts.ledger.public import member_movements
        self.assertEqual([r["balance"] for r in member_movements(self.fund_id, self.member_id)], [Money("100").amount])
        self.assertEqual([r["balance"] for r in member_movements(self.fund_id, self.member_id, "USD")],
                         [Money("7", "USD").amount])
        self.assertEqual((trial_balance(self.fund_id), trial_balance(self.fund_id, "USD")), (0, 0))

    def test_balances_are_recomputed_from_lines_alone(self):
        """No balance is stored: each query re-derives it, so it always equals
        the signed sum of the lines."""
        for n in range(5):
            post_journal(self.draft(f"b{n}", f"{10 * (n + 1)}"))
        reverse_journal(JournalEntry.objects.get(idempotency_key="b2").pk, idempotency_key="b2:rev")
        signed = sum(l.amount if l.side == "C" else -l.amount
                     for l in JournalLine.objects.filter(account__purpose="member_interest"))
        self.assertEqual(member_balances(self.fund_id)[self.member_id].amount, signed)
        self.assertEqual(member_balances(self.fund_id)[self.member_id], Money("120"))
        self.assertEqual(trial_balance(), 0)


class TenantBoundaryTests(TestCase):
    """Idempotency keys and entry ids are per tenant; row-level security is
    the boundary, the application adds only a clear error."""

    def setUp(self):
        from contexts.ledger.tests.integration.test_database_rules import Book
        self.a, self.b = Book("A"), Book("B")
        with tenant(self.b.group.tenant_id):
            self.b_entry = self.b.post("shared-key")

    def test_the_same_key_in_two_tenants_is_two_entries(self):
        with tenant(self.a.group.tenant_id):
            a_entry = self.a.post("shared-key")
        self.assertNotEqual(a_entry, self.b_entry)
        with cross_tenant("test: count both tenants' entries", actor="test"):
            self.assertEqual(JournalEntry.objects.filter(idempotency_key="shared-key").count(), 2)

    def test_another_tenants_entry_cannot_be_reversed_or_read(self):
        from contexts.ledger.application.posting import load_draft
        with tenant(self.a.group.tenant_id):
            with self.assertRaisesMessage(LedgerError, "Unknown journal entry"):
                reverse_journal(self.b_entry, idempotency_key="steal")
            with self.assertRaisesMessage(LedgerError, "Unknown journal entry"):
                load_draft(self.b_entry)
            self.assertEqual(trial_balance(), 0)
            self.assertEqual(JournalEntry.objects.count(), 0)
        with tenant(self.b.group.tenant_id):
            self.assertFalse(JournalEntry.objects.filter(reverses_id=self.b_entry).exists())


class DatabaseRuleTests(RealBooks, TestCase):
    """Writes that bypass the domain on purpose, to prove PostgreSQL refuses them."""

    def setUp(self):
        super().setUp()
        self.entry = JournalEntry.objects.get(pk=post_journal(self.draft("base")))
        self.cash, self.member = (Account.objects.get(purpose=p) for p in ("custody_cash", "member_interest"))

    def raw_entry(self, key):
        return JournalEntry.objects.create(idempotency_key=key, fingerprint="", group_id=self.group_id, fund_id=self.fund_id, kind="raw",
                                           cause_type="raw", cause_id="1")

    def test_unbalanced_entry_is_refused_at_commit(self):
        with self.assertRaisesMessage(DatabaseError, "does not balance"):
            with transaction.atomic():
                e = self.raw_entry("raw")
                JournalLine.objects.create(entry=e, account=self.cash, side="D", amount=5)
                JournalLine.objects.create(entry=e, account=self.member, side="C", amount=4)
                check_deferred()

    def test_entry_without_lines_is_refused_at_commit(self):
        with self.assertRaisesMessage(DatabaseError, "at least 2"):
            with transaction.atomic():
                self.raw_entry("empty")
                check_deferred()

    def test_non_positive_amounts_are_refused(self):
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                JournalLine.objects.create(entry=self.entry, account=self.cash, side="D", amount=0)

    def test_history_is_append_only(self):
        line = self.entry.lines.first()
        for action in (lambda: JournalLine.objects.filter(pk=line.pk).update(amount=1),
                       lambda: JournalLine.objects.filter(pk=line.pk).delete(),
                       lambda: JournalEntry.objects.filter(pk=self.entry.pk).update(memo="edited"),
                       lambda: Account.objects.filter(pk=self.cash.pk).update(currency="USD")):
            with self.assertRaisesMessage(DatabaseError, "append-only"):
                with transaction.atomic():
                    action()
