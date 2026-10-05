"""The nightly run and the operator inbox, over real groups and a simulated bank."""
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from contexts.audit.public import history
from contexts.operations.public import ItemKind, operator_inbox, run_nightly
from contexts.tenancy.public import cross_tenant
from simulators.custodian_bank import bank
from tests.scenario import Scenario


@override_settings(WEPL_OPERATIONS_EMAIL="ops@example.org")
class NightlyTests(TestCase):
    def setUp(self):
        self.a, self.b = Scenario("Umoja"), Scenario("Tujenge", account="0012345678902")
        bank.deposit(self.a.account, "1000", msisdn=self.a.m[0].msisdn, name="Wanjiku Kamau")
        bank.deposit(self.b.account, "500", msisdn=self.b.m[0].msisdn, name="Otieno")

    def test_a_quiet_night_sends_an_all_clear(self):
        steps, _ = run_nightly()
        self.assertTrue(all(s.ok for s in steps), steps)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "WEPL nightly: all clear")
        self.assertEqual(mail.outbox[0].to, ["ops@example.org"])

    def test_money_leaving_without_a_mandate_is_urgent_for_that_group_only(self):
        bank.withdraw(self.a.account, "300", narration="CASH", payee_name="Somebody", payee_msisdn="0799000111")
        steps, _ = run_nightly()
        items = operator_inbox(actor="operator:test")
        self.assertEqual([(i.group, i.kind) for i in items if i.urgent], [("Umoja", ItemKind.UNMATCHED_OUTFLOW)])
        message = mail.outbox[0]
        self.assertIn("URGENT", message.subject)
        self.assertIn("phone the officials of Umoja", message.body)
        for private in ("0799000111", "Somebody", "Wanjiku", self.a.m[0].msisdn, "300"):
            self.assertNotIn(private, message.body)

    def test_a_failing_job_does_not_stop_the_others_and_the_digest_says_so(self):
        with mock.patch("contexts.ledger.infrastructure.management.commands.check_ledger_integrity.check_books",
                        side_effect=RuntimeError("database gone")):
            steps, _ = run_nightly()
        outcome = {s.name: s.ok for s in steps}
        self.assertEqual(outcome, {"sync_accounts": True, "book_fund_transfers": True, "check_ledger_integrity": False,
                                   "deliver_outbox": True})
        self.assertIn("JOBS FAILED (check_ledger_integrity)", mail.outbox[0].subject)

    def test_an_account_the_nightly_job_missed_shows_as_not_reconciled(self):
        kinds = {(i.group, i.kind) for i in operator_inbox(actor="operator:test")}
        self.assertIn(("Umoja", ItemKind.NOT_RECONCILED), kinds)  # never reconciled yet
        run_nightly()
        self.assertFalse(operator_inbox(actor="operator:test"))

    def test_looking_at_the_inbox_is_on_the_record(self):
        operator_inbox(actor="operator:jane")
        with cross_tenant("test: read the audit trail", actor="test"):
            seen = [h for h in history(target_type="tenancy", target_id="*") if h["actor"] == "operator:jane"]
        self.assertTrue(seen and "operator inbox" in seen[-1]["data"]["reason"])
