"""WEPL's pooled collection account (ADR-0018): one bank account, many groups.
Each payment lands in exactly one group's books or is held; nothing is
guessed; no group can see the pool; and the account reconciles as a whole."""
from dataclasses import replace
from decimal import Decimal
from unittest import mock

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from contexts.custody.infrastructure.models import Collection, CollectionAccount, StatementLine
from contexts.custody.public import (CustodyError, check_reference, collect_into, open_collection_account,
                                     open_pool_alerts, receive, reconcile, reconcile_pool, record_opening_balances,
                                     sync_collections)
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, Side
from contexts.ledger.public import post_journal
from contexts.shared_kernel.money import Money
from simulators.custodian_bank import bank
from simulators.custodian_bank.connector import Faults, SimulatorConnector
from tests.scenario import Scenario

POOL = "0100WEPL0001"


class PooledCollectionTests(TestCase):
    def setUp(self):
        bank.open_account(POOL, "WEPL collections")
        open_collection_account(institution="Custodian Bank", account_number=POOL, account_name="WEPL collections",
                                connector="bank_simulator", actor="ops")
        self.a, self.b = Scenario("Umoja", account=None), Scenario("Tujenge", account=None)
        for s in (self.a, self.b):
            s.ea = collect_into(s.fund.id, account_number=POOL, actor="ops")

    def pay(self, s, member, amount, reference=None):
        return bank.deposit(POOL, amount, msisdn=member.msisdn, name="Member",
                            reference=reference or f"{s.group.payment_code}-{member.code}")

    def sync(self, connector=None):
        return sync_collections(POOL, connector or SimulatorConnector(sweep=True))

    def test_each_payment_lands_in_its_own_groups_books(self):
        self.pay(self.a, self.a.m[0], "1000")
        self.pay(self.b, self.b.m[1], "500")
        self.pay(self.a, self.a.m[1], "200", reference=f"{self.a.group.payment_code.lower()} {self.a.m[1].code}")
        result, run = self.sync()
        self.assertEqual((result.new, result.routed, result.held), (3, 3, 0))
        self.assertTrue(run.balanced, run)
        self.assertEqual((run.bank_balance, run.books_cash), (Decimal("1700"), Decimal("1700")))
        self.assertEqual(self.a.balance_of(self.a.m[0]), Money("1000"))
        self.assertEqual(self.a.balance_of(self.a.m[1]), Money("200"))
        self.assertEqual(self.b.balance_of(self.b.m[1]), Money("500"))
        for s in (self.a, self.b):
            with s.acting():
                self.assertTrue(reconcile(s.ea.id).balanced)  # its own lines, numbered 1..n, balance chained
            s.assert_sound(self)

    def test_the_bank_can_check_a_reference_before_taking_money(self):
        code = self.a.group.payment_code
        ok = check_reference(POOL, f"{code}-{self.a.m[0].code}")
        self.assertEqual((ok.accepted, ok.group_name), (True, "Umoja"))
        for wrong in (f"{code}-M99", "ZZZZZ-M01", "hello", ""):
            with self.subTest(wrong):
                self.assertFalse(check_reference(POOL, wrong).accepted)
        self.assertFalse(check_reference("another account", f"{code}-M01").accepted)

    def test_money_nobody_can_be_named_for_is_held_never_guessed(self):
        self.pay(self.a, self.a.m[0], "1000")
        self.pay(self.a, self.a.m[0], "70", reference="ZZZZZ-M01")  # no such group
        self.pay(self.a, self.a.m[0], "30", reference="for the chama")
        bank.charge(POOL, "5")  # who bears it is not yet decided
        result, run = self.sync()
        self.assertEqual((result.routed, result.held), (1, 3))
        self.assertTrue(run.balanced, run)  # what is held is accounted for at platform level
        self.assertEqual(run.held_net, Decimal("95"))
        self.assertEqual(len([x for x in open_pool_alerts(POOL) if x["kind"] == "held"]), 3)
        with self.b.acting():
            self.assertFalse(StatementLine.objects.exists())
        with self.a.acting():
            self.assertEqual(StatementLine.objects.count(), 1)

    def test_a_payout_goes_to_the_group_whose_mandate_it_quotes(self):
        for m in self.a.m[:3]:
            self.pay(self.a, m, "1000")
        self.pay(self.b, self.b.m[0], "800")
        self.sync()
        ref = self.a.approve("1200")
        bank.withdraw(POOL, "1200", narration=f"PAY {ref}")
        bank.withdraw(POOL, "100", narration="NO MANDATE")
        result, run = self.sync()
        self.assertEqual((result.routed, result.held), (1, 1))
        self.assertTrue(run.balanced, run)
        self.a.assert_sound(self)
        self.assertEqual(self.b.balance_of(self.b.m[0]), Money("800"))  # B is untouched by A's payout

    def test_a_noisy_feed_changes_nothing(self):
        for m in self.a.m:
            self.pay(self.a, m, "100")
        noisy = SimulatorConnector(Faults(duplicate_rate=1.0, reorder=True, seed=5))
        for _ in range(3):
            self.sync(noisy)
        _, run = self.sync()
        self.assertTrue(run.balanced, run)
        with self.a.acting():
            self.assertEqual(StatementLine.objects.count(), len(self.a.m))

    def test_a_crash_between_routing_and_booking_heals_on_resend(self):
        self.pay(self.a, self.a.m[0], "400")
        lines = SimulatorConnector(sweep=True).fetch(POOL)
        with mock.patch("contexts.custody.application.collections.ingest", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                receive(POOL, lines)  # recorded and routed, never booked
        with self.a.acting():
            self.assertFalse(StatementLine.objects.exists())
        self.assertFalse(reconcile_pool(POOL).balanced)  # the account-level check sees the gap
        result = receive(POOL, lines)
        self.assertEqual((result.new, result.duplicates), (0, 1))
        self.assertTrue(self.sync()[1].balanced)
        self.assertEqual(self.a.balance_of(self.a.m[0]), Money("400"))

    def test_a_conflicting_resend_is_flagged_and_not_booked(self):
        self.pay(self.a, self.a.m[0], "400")
        self.sync()
        line = SimulatorConnector(sweep=True).fetch(POOL)[0]
        result = receive(POOL, [replace(line, amount=line.amount + 1)])
        self.assertEqual(result.conflicts, 1)
        self.assertTrue(any(x["kind"] == "conflict" for x in open_pool_alerts(POOL)))
        self.assertEqual(self.a.balance_of(self.a.m[0]), Money("400"))

    def test_books_that_disagree_with_the_pooled_account_are_detected(self):
        self.pay(self.a, self.a.m[0], "400")
        self.assertTrue(self.sync()[1].balanced)
        with self.a.acting():
            key = lambda p, **kw: AccountKey(self.a.group.id, self.a.fund.id, p, **kw)
            post_journal(JournalDraft.build(
                idempotency_key="unbacked", group_id=self.a.group.id, fund_id=self.a.fund.id, kind="t",
                cause_type="t", cause_id="1",
                postings=[(key(AccountPurpose.CUSTODY_CASH, external_account_id=self.a.ea.id), Side.DEBIT, Money("50")),
                          (key(AccountPurpose.RETAINED), Side.CREDIT, Money("50"))]))
        run = self.sync()[1]
        self.assertFalse(run.balanced)
        self.assertEqual(run.difference, Decimal("50"))
        self.assertTrue(any(x["kind"] == "difference" for x in open_pool_alerts(POOL)))

    def test_a_group_sees_nothing_of_the_pool(self):
        self.pay(self.b, self.b.m[0], "900")
        self.sync()
        with self.a.acting():
            self.assertEqual((CollectionAccount.objects.count(), Collection.objects.count()), (0, 0))
            with connection.cursor() as c:
                c.execute("SELECT count(*) FROM custody_collection")
                self.assertEqual(c.fetchone()[0], 0)
            with self.assertRaises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                c.execute("INSERT INTO custody_collectionaccount (institution, account_number, account_name, "
                          "connector, currency, opened_at) VALUES ('x', 'x', 'x', 'x', 'KES', now())")

    def test_a_sub_account_takes_no_opening_balance(self):
        with self.a.acting(), self.assertRaisesMessage(CustodyError, "starts empty"):
            record_opening_balances(self.a.ea.id, statement_balance="100", member_balances={},
                                    by=self.a.m[0].id, confirmed_by=self.a.m[1].id)

    def test_one_sub_account_per_group(self):
        with self.assertRaisesMessage(CustodyError, "already collects"):
            collect_into(self.a.fund.id, account_number=POOL, actor="ops")
