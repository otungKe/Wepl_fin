"""A posted entry is sealed when its transaction commits (ledger 0005).

TestCase runs a whole test in one transaction, so it cannot show what a
later transaction may do. This plain unittest.TestCase commits for real, in a
tenant of its own, and Django runs it after its own test cases."""
import unittest

from django.db import DatabaseError, connection, transaction

from contexts.communities.public import create_group, open_fund
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, Side
from contexts.ledger.infrastructure.models import Account, JournalLine
from contexts.ledger.public import fund_position, post_journal
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import tenant


class SealedEntryTests(unittest.TestCase):
    databases = {"default"}  # so the runner builds the test database even when run alone

    def test_lines_cannot_be_added_to_an_entry_committed_earlier(self):
        group = create_group("Sealed entries", actor="test")
        with tenant(group.tenant_id):
            fund = open_fund(group.id, name="Main savings", actor="test")
            key = lambda p: AccountKey(group_id=group.id, fund_id=fund.id, purpose=p)
            entry = post_journal(JournalDraft.build(
                idempotency_key="sealed-1", group_id=group.id, fund_id=fund.id, kind="t", cause_type="t",
                cause_id="1", postings=[(key(AccountPurpose.UNEXPLAINED_OUT), Side.DEBIT, Money("100")),
                                        (key(AccountPurpose.RETAINED), Side.CREDIT, Money("100"))]))
        # committed; a later transaction tries to add a balanced pair
        with tenant(group.tenant_id):
            out, ret = (Account.objects.get(fund_id=fund.id, purpose=p) for p in ("unexplained_out", "retained"))
            with self.assertRaisesRegex(DatabaseError, "already posted"), transaction.atomic():
                JournalLine.objects.create(entry_id=entry, account=out, side="D", amount=50)
                JournalLine.objects.create(entry_id=entry, account=ret, side="C", amount=50)
        with tenant(group.tenant_id):
            self.assertEqual(JournalLine.objects.filter(entry_id=entry).count(), 2)
            self.assertEqual(fund_position(fund.id).retained, Money("100"))

    def test_truncate_is_refused_as_the_application_role(self):
        """ADR-0003 acceptance, immutable history: in a fresh transaction, with
        nothing pending, TRUNCATE is refused. The application's role has no
        TRUNCATE privilege (ADR-0027); tests/test_database_roles.py proves the
        append-only trigger refuses it even for the schema owner."""
        group = create_group("Truncate", actor="test")
        with tenant(group.tenant_id):
            fund = open_fund(group.id, name="Main savings", actor="test")
            key = lambda p: AccountKey(group_id=group.id, fund_id=fund.id, purpose=p)
            post_journal(JournalDraft.build(
                idempotency_key="kept-1", group_id=group.id, fund_id=fund.id, kind="t", cause_type="t",
                cause_id="1", postings=[(key(AccountPurpose.UNEXPLAINED_OUT), Side.DEBIT, Money("10")),
                                        (key(AccountPurpose.RETAINED), Side.CREDIT, Money("10"))]))
        with connection.cursor() as c:
            c.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            self.assertEqual(c.fetchone(), ("wepl_app", False, False))
        for table in ("ledger_journalline", "ledger_journalentry", "ledger_account"):
            with self.subTest(table), self.assertRaisesRegex(DatabaseError, "permission denied"), \
                    transaction.atomic():
                with connection.cursor() as c:
                    c.execute(f"TRUNCATE {table} CASCADE")
        with tenant(group.tenant_id):
            self.assertEqual(fund_position(fund.id).retained, Money("10"))

