from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from contexts.operations.domain.digest import StepOutcome, body, subject
from contexts.operations.domain.inbox import InboxItem, ItemKind, is_stale, ordered

NOW = datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)
OK = [StepOutcome("sync_accounts", True), StepOutcome("check_ledger_integrity", True)]


def item(group, kind, hours_ago=1, detail="KES 5,000 left on 03 Oct with no approved mandate. 0712000001"):
    return InboxItem(1, group, kind, NOW - timedelta(hours=hours_ago), detail)


class InboxOrderTests(SimpleTestCase):
    def test_urgent_first_then_oldest_first(self):
        items = [item("A", ItemKind.STATEMENT_CONFLICT, 50), item("B", ItemKind.UNMATCHED_OUTFLOW, 1),
                 item("C", ItemKind.BOOKS_FAILED, 3), item("D", ItemKind.NOT_RECONCILED, 99)]
        self.assertEqual([i.group for i in ordered(items)], ["C", "B", "D", "A"])

    def test_an_account_never_reconciled_or_not_for_36_hours_is_stale(self):
        self.assertTrue(is_stale(None, NOW))
        self.assertTrue(is_stale(NOW - timedelta(hours=37), NOW))
        self.assertFalse(is_stale(NOW - timedelta(hours=25), NOW))


class DigestTests(SimpleTestCase):
    def test_the_subject_says_what_matters_most(self):
        self.assertEqual(subject(OK, []), "WEPL nightly: all clear")
        self.assertEqual(subject(OK, [item("A", ItemKind.STATEMENT_CONFLICT)]), "WEPL nightly: 1 open")
        self.assertEqual(subject(OK, [item("A", ItemKind.UNMATCHED_OUTFLOW)]), "WEPL nightly: 1 URGENT")
        failed = OK + [StepOutcome("deliver_outbox", False, "OperationalError")]
        self.assertEqual(subject(failed, [item("A", ItemKind.UNMATCHED_OUTFLOW)]),
                         "WEPL nightly: JOBS FAILED (deliver_outbox)")

    def test_the_body_counts_by_group_and_names_who_to_phone(self):
        text = body(OK, [item("Umoja", ItemKind.UNMATCHED_OUTFLOW), item("Umoja", ItemKind.STATEMENT_CONFLICT),
                         item("Tujenge", ItemKind.NOT_RECONCILED)])
        self.assertIn("URGENT: phone the officials of Umoja.", text)
        self.assertIn("Umoja: 1 unmatched_outflow, 1 statement_conflict", text)
        self.assertIn("Tujenge: 1 not_reconciled", text)

    def test_the_email_carries_no_alert_text(self):
        """Email is not a private channel: amounts, dates and numbers stay in the inbox."""
        text = body(OK, [item("Umoja", ItemKind.UNMATCHED_OUTFLOW)])
        for private in ("0712000001", "5,000", "mandate"):
            self.assertNotIn(private, text)
        self.assertIn("Nothing is open.", body(OK, []))
