"""ADR-0003 acceptance: the checks Harry listed (2026-10-02) that no earlier
test covered directly. Each test names its checklist item. Every write here
runs as the application role, wepl_app, which row-level security binds."""
from decimal import Decimal

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from contexts.communities.public import open_fund
from contexts.custody.public import open_alerts, reconcile
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, Side
from contexts.ledger.infrastructure.models import Account, JournalEntry
from contexts.ledger.public import (account_balance, fund_position, member_balances, post_journal, reverse_journal,
                                    trial_balance)
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import cross_tenant
from simulators.custodian_bank import bank
from tests.scenario import Scenario

D, C = Side.DEBIT, Side.CREDIT


def sql(query, params=()):
    with connection.cursor() as c:
        c.execute(query, params)
        return c.fetchall() if c.description else None


def check_deferred():
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("SET CONSTRAINTS ALL DEFERRED")


class LedgerAcceptanceTests(TestCase):
    def setUp(self):
        self.s = Scenario("Acceptance", account="ACC1")
        self.enterContext(self.s.acting())
        self.g, self.f = self.s.group.id, self.s.fund.id
        self.cash = AccountKey(self.g, self.f, AccountPurpose.CUSTODY_CASH, external_account_id=self.s.ea.id)
        self.member = lambda i: AccountKey(self.g, self.f, AccountPurpose.MEMBER_INTEREST, member_id=self.s.m[i].id)
        self.retained = AccountKey(self.g, self.f, AccountPurpose.RETAINED)

    def post(self, key, postings):
        return post_journal(JournalDraft.build(idempotency_key=key, group_id=self.g, fund_id=self.f, kind="t",
                                               cause_type="t", cause_id=key, postings=postings))

    def raw_entry(self, key, tenant_id=None):
        """An entry row with no lines yet, written around the application."""
        return sql("""INSERT INTO ledger_journalentry (tenant_id, idempotency_key, fingerprint, group_id, fund_id,
                          kind, memo, cause_type, cause_id, operation_id, created_at)
                      VALUES (%s, %s, '', %s, %s, 'raw', '', 'raw', %s, '', now()) RETURNING id""",
                   (tenant_id, key, self.g, self.f, key))[0][0]

    def raw_line(self, entry, account, side, amount, tenant_id=None):
        sql("INSERT INTO ledger_journalline (tenant_id, entry_id, account_id, side, amount) VALUES (%s, %s, %s, %s, %s)",
            (tenant_id, entry, account, side, amount))

    def refused(self, message, write):
        with self.assertRaisesMessage(DatabaseError, message), transaction.atomic():
            write()
            check_deferred()

    # Balanced posting --------------------------------------------------------

    def test_a_balanced_journal_of_many_lines_commits(self):
        entry = self.post("multi", [(self.cash, D, Money("300")), (self.member(0), C, Money("100")),
                                    (self.member(1), C, Money("150")), (self.retained, C, Money("50"))])
        check_deferred()  # the commit-time balance check passes
        self.assertEqual(JournalEntry.objects.get(pk=entry).lines.count(), 4)
        self.assertEqual(trial_balance(self.f), 0)

    def test_currencies_never_balance_each_other(self):
        """Ten KES of debit cannot be balanced by ten USD of credit, in the
        database as in the domain."""
        self.post("seed", [(self.cash, D, Money("1")), (self.retained, C, Money("1"))])
        kes = Account.objects.get(purpose="custody_cash")
        from contexts.ledger.tests.integration.test_database_rules import accounts_in_any_currency
        with accounts_in_any_currency():  # funds are KES only; the balance rule must still hold if one got in
            usd = Account.objects.create(purpose="retained", group_id=self.g, fund_id=self.f, currency="USD",
                                         normal_side="C")

        def kes_against_usd():
            e = self.raw_entry("fx")
            self.raw_line(e, kes.pk, "D", 10)
            self.raw_line(e, usd.pk, "C", 10)
        self.refused("does not balance", kes_against_usd)
        from contexts.ledger.contract import LedgerError, Posting
        usd_key = AccountKey(self.g, self.f, AccountPurpose.RETAINED, currency="USD")
        with self.assertRaisesMessage(LedgerError, "does not balance"):
            JournalDraft(idempotency_key="fx", group_id=self.g, fund_id=self.f, kind="t", cause_type="t",
                         cause_id="1", postings=(Posting(self.cash, D, Money("10")),
                                                 Posting(usd_key, C, Money("10", "USD"))))

    # Empty and malformed entries --------------------------------------------

    def test_an_entry_with_one_line_cannot_commit(self):
        self.post("seed", [(self.cash, D, Money("1")), (self.retained, C, Money("1"))])
        cash = Account.objects.get(purpose="custody_cash")

        def one_line():
            self.raw_line(self.raw_entry("single"), cash.pk, "D", 5)
        self.refused("at least 2", one_line)

    def test_a_line_naming_no_real_account_cannot_commit(self):
        self.refused("unknown account", lambda: self.raw_line(self.raw_entry("ghost"), 999_999_999, "D", 5))

    # Immutable history -------------------------------------------------------

    def test_history_refuses_update_and_delete_as_the_application_role(self):
        """TRUNCATE is proven in tests/test_ledger_committed.py: PostgreSQL
        refuses to truncate a table with pending deferred checks, so it must
        run in a transaction of its own, after a real commit."""
        role = sql("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")[0]
        self.assertEqual(role, ("wepl_app", False, False))
        self.post("kept", [(self.cash, D, Money("5")), (self.retained, C, Money("5"))])
        for table in ("ledger_account", "ledger_journalentry", "ledger_journalline"):
            for statement in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}"):
                with self.subTest(statement):
                    self.refused("append-only", lambda: sql(statement))
        self.assertEqual(JournalEntry.objects.filter(idempotency_key="kept").count(), 1)

    # Balance and reconciliation ---------------------------------------------

    def test_derived_balances_equal_totals_computed_independently_in_sql(self):
        amounts = ["100", "250.50", "75.25", "40"]
        for n, a in enumerate(amounts):
            self.post(f"in{n}", [(self.cash, D, Money(a)), (self.member(n % 3), C, Money(a))])
        out = self.post("out", [(self.member(0), D, Money("30")), (self.cash, C, Money("30"))])
        reverse_journal(self.post("oops", [(self.cash, D, Money("9")), (self.retained, C, Money("9"))]),
                        idempotency_key="oops:rev")
        independent = dict(sql("""
            SELECT a.member_id, sum(CASE l.side WHEN 'C' THEN l.amount ELSE -l.amount END)
            FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
            WHERE a.fund_id = %s AND a.purpose = 'member_interest' GROUP BY a.member_id""", (self.f,)))
        self.assertEqual({k: v.amount for k, v in member_balances(self.f).items()}, independent)
        [(cash,)] = sql("""SELECT sum(CASE l.side WHEN 'D' THEN l.amount ELSE -l.amount END)
                           FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
                           WHERE a.fund_id = %s AND a.purpose = 'custody_cash'""", (self.f,))
        self.assertEqual(account_balance(self.cash).amount, cash)
        self.assertEqual(cash, sum(Decimal(a) for a in amounts) - 30)
        self.assertTrue(out and fund_position(self.f).invariant_holds)
        self.assertEqual(trial_balance(self.f), 0)

    def test_books_that_disagree_with_the_custodian_are_detected(self):
        bank.deposit("ACC1", "500", msisdn=self.s.m[3].msisdn, name="Member")
        _, run = self.s.sync()
        self.assertTrue(run.balanced)
        self.post("unbacked", [(self.cash, D, Money("50")), (self.retained, C, Money("50"))])  # no bank line
        run = reconcile(self.s.ea.id)
        self.assertFalse(run.balanced)
        self.assertEqual(run.difference.copy_abs(), Decimal("50"))
        self.assertTrue(open_alerts(self.s.group.id, kind="recon_difference"))

    # Tenant and fund isolation by direct SQL ---------------------------------

    def test_direct_sql_cannot_join_lines_across_funds(self):
        self.post("seed", [(self.cash, D, Money("1")), (self.retained, C, Money("1"))])
        welfare = open_fund(self.g, name="Welfare", actor="t")
        other_key = lambda p: AccountKey(self.g, welfare.id, p)
        post_journal(JournalDraft.build(idempotency_key="w", group_id=self.g, fund_id=welfare.id, kind="t",
                                        cause_type="t", cause_id="w",
                                        postings=[(other_key(AccountPurpose.UNEXPLAINED_OUT), D, Money("1")),
                                                  (other_key(AccountPurpose.RETAINED), C, Money("1"))]))
        w_out, w_ret = (Account.objects.get(fund_id=welfare.id, purpose=p).pk for p in ("unexplained_out", "retained"))

        def cross_fund():
            e = self.raw_entry("xf")
            self.raw_line(e, w_out, "D", 5)
            self.raw_line(e, w_ret, "C", 5)
        self.refused("group and fund", cross_fund)



class CrossTenantSqlTests(TestCase):
    """Tenant and fund isolation, the tenant half: even inside a declared
    cross-tenant operation, where every row is visible, direct SQL cannot
    put another tenant's accounts on an entry."""

    def test_direct_sql_cannot_join_lines_across_tenants(self):
        a, b = Scenario("Mine", account="ACC3"), Scenario("Neighbour", account="ACC4")
        with b.acting():
            key = lambda p: AccountKey(b.group.id, b.fund.id, p)
            post_journal(JournalDraft.build(
                idempotency_key="n", group_id=b.group.id, fund_id=b.fund.id, kind="t", cause_type="t", cause_id="n",
                postings=[(key(AccountPurpose.UNEXPLAINED_OUT), D, Money("1")),
                          (key(AccountPurpose.RETAINED), C, Money("1"))]))
        with cross_tenant("test: direct SQL with every row visible", actor="t"):
            n_out, n_ret = (Account.objects.get(fund_id=b.fund.id, purpose=p).pk
                            for p in ("unexplained_out", "retained"))

            def cross_tenant_lines():
                [(mine,)] = sql("""INSERT INTO ledger_journalentry (tenant_id, idempotency_key, fingerprint, group_id,
                                       fund_id, kind, memo, cause_type, cause_id, operation_id, created_at)
                                   VALUES (%s, 'xt', '', %s, %s, 'raw', '', 'raw', 'xt', '', now()) RETURNING id""",
                                (a.tenant_id, a.group.id, a.fund.id))
                sql("INSERT INTO ledger_journalline (tenant_id, entry_id, account_id, side, amount) "
                    "VALUES (%s, %s, %s, 'D', 5), (%s, %s, %s, 'C', 5)",
                    (a.tenant_id, mine, n_out, a.tenant_id, mine, n_ret))
            with self.assertRaisesMessage(DatabaseError, "one tenant"), transaction.atomic():
                cross_tenant_lines()
                check_deferred()
            with connection.cursor() as c:
                c.execute("SET CONSTRAINTS ALL DEFERRED")
        with a.acting():
            self.assertFalse(JournalEntry.objects.filter(idempotency_key="xt").exists())
