"""What PostgreSQL refuses on its own, whatever code writes to the ledger
(ledger 0005; docs/architecture/review-ledger-infrastructure.md). Each test is
one write the database used to accept."""
from django.db import IntegrityError, connection, transaction
from django.db.utils import DatabaseError
from django.test import TestCase

from contexts.communities.public import create_group, open_fund
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, LedgerError, Side
from contexts.ledger.infrastructure.accounts import resolve
from contexts.ledger.infrastructure.models import Account, JournalEntry, JournalLine
from contexts.ledger.public import post_journal, reverse_journal
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import cross_tenant, tenant

D, C = Side.DEBIT, Side.CREDIT


def check_deferred():
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("SET CONSTRAINTS ALL DEFERRED")


def as_a_later_transaction():
    """Within one test transaction, forget which entries this transaction
    opened, as a later transaction would. (tests/test_ledger_committed.py
    shows the same against a real commit.)"""
    with connection.cursor() as c:
        c.execute("SELECT set_config('wepl.ledger_open_entries', '', true)")


class Book:
    def __init__(self, name):
        self.group = create_group(name, actor="t")
        with tenant(self.group.tenant_id):
            self.fund = open_fund(self.group.id, name="Main savings", actor="t")

    def key(self, purpose, fund=None):
        return AccountKey(group_id=self.group.id, fund_id=(fund or self.fund).id, purpose=purpose)

    def post(self, idem, amount="100", fund=None):
        return post_journal(JournalDraft.build(
            idempotency_key=idem, group_id=self.group.id, fund_id=(fund or self.fund).id, kind="t", cause_type="t",
            cause_id=idem, postings=[(self.key(AccountPurpose.UNEXPLAINED_OUT, fund), D, Money(amount)),
                                     (self.key(AccountPurpose.RETAINED, fund), C, Money(amount))]))

    def accounts(self):
        return (Account.objects.get(fund_id=self.fund.id, purpose="unexplained_out"),
                Account.objects.get(fund_id=self.fund.id, purpose="retained"))

    def raw_entry(self, idem, **kw):
        cause = (("journal_entry", str(kw["reverses_id"])) if kw.get("reverses_id") else ("raw", idem))
        return JournalEntry.objects.create(idempotency_key=idem, fingerprint="", group_id=self.group.id,
                                           fund_id=self.fund.id, kind="raw", cause_type=cause[0], cause_id=cause[1],
                                           **kw)


class DatabaseRuleTests(TestCase):
    def setUp(self):
        self.a, self.b = Book("A"), Book("B")
        with tenant(self.b.group.tenant_id):
            self.b_entry = self.b.post("b1")
            self.b_out, self.b_ret = self.b.accounts()
        self.enterContext(tenant(self.a.group.tenant_id))
        self.a_entry = self.a.post("a1")
        self.a_out, self.a_ret = self.a.accounts()

    def refused(self, message, write):
        with self.assertRaisesMessage(DatabaseError, message), transaction.atomic():
            write()
            check_deferred()

    def lines(self, entry_id, debit, credit, amount=5):
        JournalLine.objects.create(entry_id=entry_id, account=debit, side="D", amount=amount)
        JournalLine.objects.create(entry_id=entry_id, account=credit, side="C", amount=amount)

    def test_p1_a_posted_entry_takes_no_new_lines(self):
        as_a_later_transaction()
        self.refused("already posted", lambda: self.lines(self.a_entry, self.a_out, self.a_ret))
        self.assertEqual(JournalLine.objects.filter(entry_id=self.a_entry).count(), 2)

    def test_p2_an_entry_cannot_post_to_another_tenants_accounts(self):
        self.refused("unknown account", lambda: self.lines(self.a.raw_entry("a2").pk, self.b_out, self.b_ret))

    def test_p5_no_line_joins_another_tenants_entry(self):
        self.refused("unknown journal entry", lambda: self.lines(self.b_entry, self.a_out, self.a_ret))

    def test_p6_a_reversal_stays_in_its_tenant(self):
        self.refused("outside its tenant", lambda: self.a.raw_entry("a3", reverses_id=self.b_entry))

    def test_p7_an_entrys_lines_stay_in_its_group_and_fund(self):
        other = open_fund(self.a.group.id, name="Welfare", actor="t")
        self.a.post("seed-welfare", fund=other)
        welfare_out = Account.objects.get(fund_id=other.id, purpose="unexplained_out")
        welfare_ret = Account.objects.get(fund_id=other.id, purpose="retained")
        self.refused("group and fund", lambda: self.lines(self.a.raw_entry("a4").pk, welfare_out, welfare_ret))

    def test_p8_a_reversal_must_mirror_its_original(self):
        def half_reversal():
            e = self.a.raw_entry("a5", reverses_id=self.a_entry)
            self.lines(e.pk, self.a_out, self.a_ret, amount=40)  # same direction, wrong amount
        self.refused("does not mirror", half_reversal)
        reversal = reverse_journal(self.a_entry, idempotency_key="a1-reversal")  # the real one still works
        check_deferred()
        self.assertEqual(JournalEntry.objects.get(pk=reversal).reverses_id, self.a_entry)

    def test_p3_an_accounts_normal_side_follows_its_purpose(self):
        self.refused("normal_side_follows_purpose", lambda: Account.objects.create(
            purpose="custody_cash", group_id=self.a.group.id, fund_id=self.a.fund.id, external_account_id=9,
            normal_side="C"))

    def test_purpose_and_currency_are_known_values(self):
        for kw, rule in (({"purpose": "anything"}, "purpose_known"), ({"currency": "kes"}, "currency_code")):
            with self.subTest(kw):
                fields = {"purpose": "retained", "group_id": self.a.group.id, "fund_id": self.a.fund.id,
                          "normal_side": "C", **kw}
                self.refused(rule, lambda: Account.objects.create(**fields))

    def test_a_second_reversal_racing_the_first_is_reported_as_such(self):
        reverse_journal(self.a_entry, idempotency_key="r1")
        from contexts.ledger.application.posting import load_draft
        racing = load_draft(self.a_entry).reversal(entry_id=self.a_entry, idempotency_key="r2")
        with self.assertRaisesMessage(LedgerError, "already been reversed"):
            post_journal(racing)  # skips reverse_journal's early check, as a concurrent caller would


class ResolveTests(TestCase):
    def setUp(self):
        self.a, self.b = Book("A"), Book("B")

    def test_p2_even_where_every_row_is_visible_a_line_stays_in_its_tenant(self):
        with tenant(self.b.group.tenant_id):
            self.b.post("b1")
            b_out, b_ret = self.b.accounts()
        with cross_tenant("test: every row visible, tenants still checked", actor="t"):
            with self.assertRaisesMessage(DatabaseError, "one tenant"), transaction.atomic():
                entry = self.a.raw_entry("a2", tenant_id=self.a.group.tenant_id)
                JournalLine.objects.create(entry=entry, account=b_out, side="D", amount=5, tenant_id=entry.tenant_id)

    def test_p4_a_key_naming_another_tenants_fund_is_refused(self):
        """Before ADR-0017 a mistaken key in A wrote an account in A naming B's
        fund (harmless to B, because keys are unique per tenant). Now the
        database refuses that account outright, and B is unaffected."""
        key = self.b.key(AccountPurpose.UNATTRIBUTED_IN)
        with tenant(self.a.group.tenant_id):
            with self.assertRaisesMessage(IntegrityError, "not its tenant"):
                resolve(key)
            self.assertFalse(Account.objects.filter(fund_id=self.b.fund.id).exists())
        with tenant(self.b.group.tenant_id):
            in_b = resolve(key)
            self.assertEqual(resolve(key).pk, in_b.pk)

    def test_an_account_of_another_group_is_a_ledger_error(self):
        with tenant(self.a.group.tenant_id):
            resolve(self.a.key(AccountPurpose.RETAINED))
            wrong = AccountKey(group_id=self.b.group.id, fund_id=self.a.fund.id, purpose=AccountPurpose.RETAINED)
            with self.assertRaisesMessage(LedgerError, "another group"):
                resolve(wrong)

    def test_a_refusal_other_than_a_lost_race_is_not_hidden(self):
        bad = AccountKey(group_id=self.a.group.id, fund_id=self.a.fund.id, purpose=AccountPurpose.RETAINED,
                         currency="kes")
        with tenant(self.a.group.tenant_id), self.assertRaisesMessage(IntegrityError, "currency_code"):
            resolve(bad)  # was reported as Account.DoesNotExist


class EntryIdentityRuleTests(TestCase):
    """What the domain requires of an entry's identity, PostgreSQL requires
    too (ledger 0010), so a raw write cannot weaken idempotency or tracing."""

    def setUp(self):
        self.a = Book("A")
        self.enterContext(tenant(self.a.group.tenant_id))
        self.entry = self.a.post("a1")

    def create(self, **kw):
        fields = dict(idempotency_key="raw", fingerprint="", group_id=self.a.group.id, fund_id=self.a.fund.id,
                      kind="reversal", cause_type="journal_entry", cause_id=str(self.entry), reverses_id=None)
        return JournalEntry.objects.create(**{**fields, **kw})

    def refused(self, rule, **kw):
        with self.assertRaisesMessage(DatabaseError, rule), transaction.atomic():
            self.create(**kw)

    def test_a_reversals_cause_is_the_entry_it_reverses(self):
        other = self.a.post("a2")
        self.refused("ledger_reversal_names_its_original", reverses_id=self.entry, cause_id=str(other))
        self.refused("ledger_reversal_names_its_original", reverses_id=self.entry, cause_type="t")

    def test_a_fund_transfer_leg_reverses_nothing(self):
        self.refused("ledger_reversal_names_its_original", reverses_id=self.entry, kind="fund_transfer_out")

    def test_every_entry_has_a_kind_and_a_cause(self):
        for field in ("kind", "cause_type", "cause_id"):
            with self.subTest(field):
                self.refused("ledger_entry_has_kind_and_cause", **{field: ""})
