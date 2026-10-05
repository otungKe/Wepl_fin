"""Posting a move between funds (ADR-0024): both entries or neither,
idempotently, and PostgreSQL holds the pair to the same rule at commit
(ledger 0009) whatever code writes it."""
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase

from contexts.communities.public import add_member, open_fund
from contexts.custody.public import link_external_account
from contexts.ledger.contract import (TRANSFER_IN, TRANSFER_OUT, AccountKey, AccountPurpose, FundTransfer,
                                      JournalDraft, LedgerError, Side)
from contexts.ledger.infrastructure.accounts import resolve
from contexts.ledger.infrastructure.models import JournalEntry, JournalLine
from contexts.ledger.public import (check_books, fund_position, member_balances, post_journal, post_transfer,
                                    reverse_journal, trial_balance)
from contexts.ledger.tests.integration.test_database_rules import Book, check_deferred
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import tenant

D, C = Side.DEBIT, Side.CREDIT


class TransferPostingTests(TestCase):
    def setUp(self):
        self.b = Book("A")
        self.enterContext(tenant(self.b.group.tenant_id))
        self.general = self.b.fund
        self.welfare = open_fund(self.b.group.id, name="Welfare", actor="t")
        self.bank = link_external_account(self.general.id, institution="Custodian Bank", account_number="0099",
                                          account_name="A", connector="bank_simulator", actor="t").id
        self.m = {i: add_member(self.b.group.id, msisdn=f"071200000{i}", name=f"M{i}", actor="t").id for i in (1, 2)}
        # General holds 100 for member 1 and 50 for member 2, at the bank
        self.cash_in("seed", self.general, {self.m[1]: "100", self.m[2]: "50"})

    def k(self, fund, purpose, member=None):
        return AccountKey(group_id=self.b.group.id, fund_id=fund.id, purpose=purpose, member_id=member,
                          external_account_id=self.bank if purpose is AccountPurpose.CUSTODY_CASH else None)

    def cash_in(self, idem, fund, members):
        total = sum((Money(a) for a in members.values()), Money.zero())
        post_journal(JournalDraft.build(
            idempotency_key=idem, group_id=self.b.group.id, fund_id=fund.id, kind="contribution", cause_type="t",
            cause_id=idem, postings=[(self.k(fund, AccountPurpose.CUSTODY_CASH), D, total),
                                     *[(self.k(fund, AccountPurpose.MEMBER_INTEREST, m), C, Money(a))
                                       for m, a in members.items()]]))

    def leg(self, fund, kind, cause, postings):
        return JournalDraft.build(idempotency_key=f"{cause}:{kind}", group_id=self.b.group.id, fund_id=fund.id,
                                  kind=kind, cause_type="governance.fund_transfer", cause_id=cause, postings=postings)

    def transfer(self, cause="1", shares=(("1", "20"), ("2", "10"))):
        total = sum((Money(a) for _, a in shares), Money.zero())
        mem = lambda f, side: [(self.k(f, AccountPurpose.MEMBER_INTEREST, self.m[int(m)]), side, Money(a)) for m, a in shares]
        return FundTransfer(
            self.leg(self.general, TRANSFER_OUT, cause, [*mem(self.general, D),
                                                         (self.k(self.general, AccountPurpose.CUSTODY_CASH), C, total)]),
            self.leg(self.welfare, TRANSFER_IN, cause, [(self.k(self.welfare, AccountPurpose.CUSTODY_CASH), D, total),
                                                        *mem(self.welfare, C)]))

    def test_a_transfer_moves_the_money_and_keeps_its_owners(self):
        out_id, in_id = post_transfer(self.transfer())
        check_deferred()
        self.assertEqual(fund_position(self.general.id).cash, Money("120"))
        self.assertEqual(fund_position(self.welfare.id).cash, Money("30"))
        self.assertEqual(member_balances(self.general.id), {self.m[1]: Money("80"), self.m[2]: Money("40")})
        self.assertEqual(member_balances(self.welfare.id), {self.m[1]: Money("20"), self.m[2]: Money("10")})
        for f in (self.general, self.welfare):
            self.assertEqual(trial_balance(f.id), 0)
            self.assertTrue(fund_position(f.id).invariant_holds)
        self.assertEqual(JournalEntry.objects.get(pk=out_id).fund_id, self.general.id)
        self.assertEqual(JournalEntry.objects.get(pk=in_id).fund_id, self.welfare.id)
        self.assertTrue(all(c.passed and c.unpaired_transfers == 0 for c in check_books()))

    def test_distinct_transfers_accumulate_and_a_replay_changes_nothing(self):
        first = post_transfer(self.transfer("1"))
        post_transfer(self.transfer("2"))
        self.assertEqual(fund_position(self.welfare.id).cash, Money("60"))
        lines = JournalLine.objects.count()
        self.assertEqual(post_transfer(self.transfer("1")), first)
        self.assertEqual((JournalLine.objects.count(), fund_position(self.welfare.id).cash), (lines, Money("60")))
        with self.assertRaisesMessage(LedgerError, "already used for a different entry"):
            post_transfer(self.transfer("1", shares=(("1", "30"),)))

    def test_half_a_transfer_is_refused_by_the_ledger(self):
        with self.assertRaisesMessage(LedgerError, "posted together"):
            post_journal(self.transfer().out)

    def test_postgresql_refuses_half_a_transfer_at_commit(self):
        with self.assertRaisesMessage(DatabaseError, "exactly one entry out and one in"), transaction.atomic():
            self._raw(self.transfer().out)
            check_deferred()

    def test_postgresql_refuses_a_pair_that_changes_owners(self):
        t = self.transfer()
        other = self.leg(self.welfare, TRANSFER_IN, "1", [(self.k(self.welfare, AccountPurpose.CUSTODY_CASH), D,
                                                           Money("30")),
                                                          (self.k(self.welfare, AccountPurpose.RETAINED), C, Money("30"))])
        with self.assertRaisesMessage(DatabaseError, "exactly what the source gives"), transaction.atomic():
            self._raw(t.out)
            self._raw(other)
            check_deferred()

    def test_a_transfer_is_never_reversed(self):
        out_id, _ = post_transfer(self.transfer())
        with self.assertRaisesMessage(LedgerError, "half of a fund transfer"):
            reverse_journal(out_id, idempotency_key="undo")
        with self.assertRaisesMessage(DatabaseError, "never reversed"), transaction.atomic():
            JournalEntry.objects.create(idempotency_key="raw-undo", fingerprint="", group_id=self.b.group.id,
                                        fund_id=self.general.id, kind="reversal", cause_type="journal_entry",
                                        cause_id=str(out_id), reverses_id=out_id)

    def test_the_nightly_check_fails_a_fund_with_an_unpaired_half(self):
        post_transfer(self.transfer())
        with mock.patch("contexts.ledger.application.integrity._unpaired_transfers", return_value=1):
            checks = check_books()
        self.assertTrue(checks and not any(c.passed for c in checks))

    def _raw(self, draft):
        """Write an entry straight to the tables, as code bypassing the ledger would."""
        e = JournalEntry.objects.create(idempotency_key=draft.idempotency_key, fingerprint=draft.fingerprint(),
                                        group_id=draft.group_id, fund_id=draft.fund_id, kind=draft.kind,
                                        cause_type=draft.cause_type, cause_id=draft.cause_id)
        JournalLine.objects.bulk_create(JournalLine(entry=e, account=resolve(p.account), side=p.side.value,
                                                    amount=p.amount.amount) for p in draft.postings)
