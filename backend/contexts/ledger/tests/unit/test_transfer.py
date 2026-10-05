"""A move between funds is two entries that mirror each other (ADR-0024)."""
from django.test import SimpleTestCase

from contexts.ledger.contract import (TRANSFER_IN, TRANSFER_OUT, AccountKey, AccountPurpose, FundTransfer,
                                      JournalDraft, LedgerError, Side)
from contexts.shared_kernel.money import Money

D, C = Side.DEBIT, Side.CREDIT
G, GENERAL, WELFARE, BANK = 1, 10, 20, 7


def key(fund, purpose, member=None, bank=BANK, group=G):
    return AccountKey(group_id=group, fund_id=fund, purpose=purpose, member_id=member,
                      external_account_id=bank if purpose is AccountPurpose.CUSTODY_CASH else None)


def leg(fund, kind, postings, *, group=G, cause="1", idem=None):
    return JournalDraft.build(idempotency_key=idem or f"{kind}:{cause}", group_id=group, fund_id=fund, kind=kind,
                              cause_type="governance.fund_transfer", cause_id=cause, postings=postings)


def out(fund=GENERAL, members=((1, "60"), (2, "40")), **kw):
    m = [(key(fund, AccountPurpose.MEMBER_INTEREST, i, group=kw.get("group", G)), D, Money(a)) for i, a in members]
    total = sum((Money(a) for _, a in members), Money.zero())
    return leg(fund, TRANSFER_OUT, [*m, (key(fund, AccountPurpose.CUSTODY_CASH, group=kw.get("group", G)), C, total)],
               **kw)


def into(fund=WELFARE, members=((1, "60"), (2, "40")), bank=BANK, **kw):
    m = [(key(fund, AccountPurpose.MEMBER_INTEREST, i), C, Money(a)) for i, a in members]
    total = sum((Money(a) for _, a in members), Money.zero())
    return leg(fund, TRANSFER_IN, [(key(fund, AccountPurpose.CUSTODY_CASH, bank=bank), D, total), *m], **kw)


class FundTransferTests(SimpleTestCase):
    def test_a_mirrored_pair_is_a_transfer(self):
        t = FundTransfer(out(), into())
        self.assertEqual((t.out.fund_id, t.into.fund_id), (GENERAL, WELFARE))

    def test_the_group_s_own_money_can_move(self):
        FundTransfer(leg(GENERAL, TRANSFER_OUT, [(key(GENERAL, AccountPurpose.RETAINED), D, Money("5")),
                                                (key(GENERAL, AccountPurpose.CUSTODY_CASH), C, Money("5"))]),
                     leg(WELFARE, TRANSFER_IN, [(key(WELFARE, AccountPurpose.CUSTODY_CASH), D, Money("5")),
                                                (key(WELFARE, AccountPurpose.RETAINED), C, Money("5"))]))

    def test_refusals(self):
        cases = {
            "a fund_transfer_out entry and a fund_transfer_in entry": (into(GENERAL), into()),
            "same group": (out(group=2), into()),
            "two different funds": (out(), into(GENERAL)),
            "share its cause": (out(), into(cause="2")),
            "same bank account": (out(), into(bank=8)),
            "same owners, same amounts": (out(), into(members=((1, "50"), (2, "50")))),
        }
        for message, (o, i) in cases.items():
            with self.subTest(message), self.assertRaisesMessage(LedgerError, message):
                FundTransfer(o, i)

    def test_ownership_never_changes_hands(self):
        # members' money cannot become the group's, nor another member's
        group_in = leg(WELFARE, TRANSFER_IN, [(key(WELFARE, AccountPurpose.CUSTODY_CASH), D, Money("100")),
                                              (key(WELFARE, AccountPurpose.RETAINED), C, Money("100"))])
        with self.assertRaisesMessage(LedgerError, "same owners"):
            FundTransfer(out(), group_in)
        with self.assertRaisesMessage(LedgerError, "same owners"):
            FundTransfer(out(), into(members=((1, "60"), (3, "40"))))

    def test_unattributed_money_never_moves(self):
        o = leg(GENERAL, TRANSFER_OUT, [(key(GENERAL, AccountPurpose.UNATTRIBUTED_IN), D, Money("5")),
                                        (key(GENERAL, AccountPurpose.CUSTODY_CASH), C, Money("5"))])
        i = leg(WELFARE, TRANSFER_IN, [(key(WELFARE, AccountPurpose.CUSTODY_CASH), D, Money("5")),
                                       (key(WELFARE, AccountPurpose.UNATTRIBUTED_IN), C, Money("5"))])
        with self.assertRaisesMessage(LedgerError, "Only a member's or the group's own money"):
            FundTransfer(o, i)

    def test_cash_must_leave_the_source(self):
        backwards = leg(GENERAL, TRANSFER_OUT, [(key(GENERAL, AccountPurpose.CUSTODY_CASH), D, Money("5")),
                                                (key(GENERAL, AccountPurpose.RETAINED), C, Money("5"))])
        with self.assertRaisesMessage(LedgerError, "leaves the source fund's cash"):
            FundTransfer(backwards, into())
