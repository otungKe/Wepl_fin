"""The nightly integrity check: it records, alerts, and never corrects."""
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.audit.infrastructure.models import AuditEvent
from contexts.ledger.contract import FundPosition
from contexts.ledger.contract import AccountKey, AccountPurpose
from contexts.ledger.infrastructure.accounts import resolve
from contexts.ledger.infrastructure.models import Account, IntegrityCheck, JournalEntry, JournalLine
from contexts.ledger.public import check_books
from contexts.ledger.tests.integration.test_database_rules import Book, accounts_in_any_currency
from contexts.notifications.public import topics_since
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import cross_tenant, tenant

BROKEN = FundPosition(cash=Money("100"), member_interests=Money("90"), unattributed=Money("0"),
                      retained=Money("0"), unexplained_out=Money("0"))  # a query bug the check must notice


@contextmanager
def balance_rules_off():
    """Turn off 0002's commit-time balance checks, as a superuser, a restore
    or a dropped trigger would. The application role can do this only
    because it owns the tables (review 2026-10-06, H1); the test's rollback
    turns them back on, and so does the end of this block."""
    rules = (("ledger_journalline", "ledger_line_balanced"), ("ledger_journalentry", "ledger_entry_has_lines"))
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")  # ALTER TABLE refuses while trigger events are pending
        c.execute("SET CONSTRAINTS ALL DEFERRED")
        for table, trigger in rules:
            c.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
    try:
        yield
    finally:
        with connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
            c.execute("SET CONSTRAINTS ALL DEFERRED")
            for table, trigger in rules:
                c.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


class IntegrityCheckTests(TestCase):
    def setUp(self):
        self.a, self.b = Book("A"), Book("B")
        with tenant(self.b.group.tenant_id):
            self.b.post("b1")
        with tenant(self.a.group.tenant_id):
            self.a.post("a1", "100")
            self.a.post("a2", "40")
        self.since = timezone.now()

    def in_a(self):
        return tenant(self.a.group.tenant_id)

    def test_sound_books_pass_and_are_recorded_without_an_alert(self):
        self.enterContext(self.in_a())
        lines = JournalLine.objects.count()
        checks = check_books()
        self.assertEqual([(c.fund_id, c.currency, c.passed) for c in checks], [(self.a.fund.id, "KES", True)])
        c = checks[0]
        self.assertEqual((c.trial_balance, c.retained, c.unexplained_out), (0, Decimal("140"), Decimal("140")))
        self.assertEqual(c.lines, 4)
        self.assertTrue(c.operation_id.startswith("ledger.integrity_check:"))
        self.assertEqual(JournalLine.objects.count(), lines)  # it reads the books, never writes them
        self.assertNotIn("ops.ledger_integrity_failure", topics_since(self.since))

    def test_each_tenant_checks_and_sees_only_its_own_books(self):
        with self.in_a():
            check_books()
            self.assertEqual(set(IntegrityCheck.objects.values_list("fund_id", flat=True)), {self.a.fund.id})
        with tenant(self.b.group.tenant_id):
            self.assertFalse(IntegrityCheck.objects.exists())
            self.assertEqual([c.fund_id for c in check_books()], [self.b.fund.id])

    def test_a_failure_is_recorded_audited_and_alerted_once(self):
        self.enterContext(self.in_a())
        cash_short = ({"custody_cash": (Decimal("100"), Decimal("0")), "member_interest": (Decimal("0"), Decimal("90"))}, 2)
        with mock.patch("contexts.ledger.infrastructure.books.totals_by_purpose", return_value=cash_short):
            [c] = check_books()
        self.assertFalse(c.passed)
        self.assertFalse(c.invariant_holds)
        self.assertEqual(c.trial_balance, Decimal("10"))
        self.assertEqual(topics_since(self.since).count("ops.ledger_integrity_failure"), 1)
        self.assertTrue(AuditEvent.objects.filter(action="ledger.integrity_check_failed",
                                                  target_id=str(self.a.fund.id)).exists())
        with mock.patch("contexts.ledger.application.integrity.trial_balance", return_value=Decimal("0.01")):
            [again] = check_books()
        self.assertFalse(again.passed)  # the trial balance query disagrees with the journal
        self.assertEqual((again.trial_balance, again.invariant_holds, again.queries_agree), (0, True, False))
        self.assertEqual(topics_since(self.since).count("ops.ledger_integrity_failure"), 2)  # one per failed check

    def test_a_balance_query_that_is_wrong_but_consistent_fails_the_check(self):
        """A bug in fund_position that returns a plausible, self-consistent
        position (here: nothing held) used to pass, because the check read
        the books through that same query. It now sums the lines itself."""
        self.enterContext(self.in_a())
        empty = FundPosition(*(Money("0"),) * 5)
        self.assertTrue(empty.invariant_holds)
        with mock.patch("contexts.ledger.application.integrity.fund_position", return_value=empty):
            [c] = check_books()
        self.assertEqual((c.passed, c.queries_agree, c.invariant_holds), (False, False, True))
        self.assertEqual((c.retained, c.unexplained_out), (Decimal("140"), Decimal("140")))  # what the lines say

    def test_results_are_append_only_and_cannot_claim_a_pass_they_did_not_get(self):
        self.enterContext(self.in_a())
        [c] = check_books()
        with self.assertRaisesMessage(DatabaseError, "append-only"), transaction.atomic():
            IntegrityCheck.objects.filter(pk=c.pk).update(passed=False)
        with self.assertRaises(DatabaseError), transaction.atomic():
            IntegrityCheck.objects.create(fund_id=c.fund_id, currency="KES", trial_balance=Decimal("5"), cash=0,
                                          member_interests=0, unattributed=0, retained=0, unexplained_out=0,
                                          invariant_holds=True, passed=True, lines=0)

    def test_the_nightly_command_checks_every_tenant_and_fails_loudly(self):
        call_command("check_ledger_integrity", stdout=mock.MagicMock(), stderr=mock.MagicMock())
        with self.in_a():
            self.assertTrue(IntegrityCheck.objects.filter(fund_id=self.a.fund.id, passed=True).exists())
        with tenant(self.b.group.tenant_id):
            self.assertTrue(IntegrityCheck.objects.filter(fund_id=self.b.fund.id, passed=True).exists())
        with mock.patch("contexts.ledger.application.integrity.fund_position", return_value=BROKEN):
            with self.assertRaisesMessage(CommandError, "failed the integrity check"):
                call_command("check_ledger_integrity", stdout=mock.MagicMock(), stderr=mock.MagicMock())


class BypassedRulesTests(TestCase):
    """Books that PostgreSQL would have refused, written with its checks
    turned off: the nightly check must fail them, which is its whole job."""

    def setUp(self):
        self.a = Book("A")
        self.enterContext(tenant(self.a.group.tenant_id))
        self.a.post("a1", "100")
        self.out, self.ret = self.a.accounts()

    def entry(self, key, *lines):
        e = JournalEntry.objects.create(idempotency_key=key, fingerprint="", group_id=self.a.group.id,
                                        fund_id=self.a.fund.id, kind="raw", cause_type="raw", cause_id=key)
        for account, side, amount in lines:
            JournalLine.objects.create(entry=e, account=account, side=side, amount=amount)

    def test_two_unbalanced_entries_that_offset_each_other_fail(self):
        """Their fund still nets to zero, so a check of the fund's totals
        alone passed them."""
        with balance_rules_off():
            self.entry("over", (self.out, "D", 10), (self.ret, "C", 9))
            self.entry("under", (self.out, "D", 9), (self.ret, "C", 10))
        [c] = check_books()
        self.assertEqual((c.trial_balance, c.invariant_holds), (0, True))
        self.assertEqual((c.broken_entries, c.passed), (2, False))

    def test_an_entry_without_lines_fails(self):
        with balance_rules_off():
            self.entry("empty")
        [c] = check_books()
        self.assertEqual((c.broken_entries, c.passed), (1, False))

    def test_a_surplus_in_one_currency_cannot_hide_a_shortfall_in_another(self):
        """Before 2026-10-06 the KES check's trial balance summed every
        currency of the fund: 10 KES out and 10 USD in made zero."""
        with accounts_in_any_currency():
            usd = resolve(AccountKey(self.a.group.id, self.a.fund.id, AccountPurpose.RETAINED, currency="USD"))
        with balance_rules_off():
            self.entry("mixed", (self.out, "D", 10), (usd, "C", 10))
        checks = {c.currency: c for c in check_books()}
        self.assertEqual((checks["KES"].trial_balance, checks["USD"].trial_balance), (Decimal("10"), Decimal("-10")))
        self.assertFalse(any(c.passed for c in checks.values()))
        self.assertEqual(checks["KES"].broken_entries, 1)


class NightlyCommandTests(TestCase):
    def test_one_tenant_that_cannot_be_checked_does_not_stop_the_others(self):
        a, b = Book("A"), Book("B")
        for book in (a, b):
            with tenant(book.group.tenant_id):
                book.post("x")
        real, calls = check_books, []

        def first_one_fails():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database hiccup")
            return real()

        err = mock.MagicMock()
        with mock.patch("contexts.ledger.infrastructure.management.commands.check_ledger_integrity.check_books",
                        side_effect=first_one_fails):
            with self.assertRaisesMessage(CommandError, "1 tenant(s) could not be checked"):
                call_command("check_ledger_integrity", stdout=mock.MagicMock(), stderr=err)
        self.assertEqual(len(calls), 2)
        self.assertIn("COULD NOT CHECK", "".join(str(c) for c in err.write.call_args_list))
        with cross_tenant("test: count both tenants' results", actor="test"):
            self.assertEqual(IntegrityCheck.objects.filter(fund_id__in=[a.fund.id, b.fund.id], passed=True).count(), 1)
