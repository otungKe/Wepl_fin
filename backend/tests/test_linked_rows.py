"""A row and every row it refers to belong to the same tenant (ADR-0017).

Foreign key checks ignore row-level security, so before ADR-0017 a write in
tenant A could name tenant B's group, member, fund or ledger entry: the
probe of 2026-10-01 had each write below accepted. These tests go around
the application on purpose, inside a tenant and inside a declared
cross-tenant operation, and show PostgreSQL refusing every one."""
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from contexts.custody.infrastructure.models import LineResolution, PayerMapping, StatementLine
from contexts.governance.infrastructure.models import Approval, CapabilityChange, Mandate
from contexts.ledger.contract import AccountKey, AccountPurpose, JournalDraft, Side
from contexts.ledger.infrastructure.models import Account, JournalEntry
from contexts.ledger.public import post_journal
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import cross_tenant
from simulators.custodian_bank import bank
from tests.scenario import Scenario
from tests.test_tenancy import sql, tenant_scoped_tables

# What an ADR-0017 refusal says: a composite key's name, or a plain-id check's
# message. Matching it means the write failed for this rule, not another.
REFUSED = r"_same_tenant|not its tenant|not of its"

# Links that are plain ids by design (ADR-0004), each checked by a trigger
# installed by the context that already depends on the other (ADR-0017).
PLAIN_ID_CHECKS = {
    ("ledger_journalentry", "communities_entry_names_its_own_fund"),
    ("ledger_account", "communities_account_names_its_own_fund"),
    ("ledger_account", "communities_account_names_its_own_member"),
    ("ledger_account", "custody_cash_names_its_own_account"),
    ("custody_lineresolution", "custody_resolution_names_its_own_entry"),
    ("governance_mandate", "custody_mandate_names_its_own_line"),
}


class EveryLinkCarriesTheTenantTests(TestCase):
    """The guard: a new key between tenant-scoped tables without the tenant
    fails the build, not a security review."""

    def test_every_key_between_tenant_scoped_tables_includes_the_tenant(self):
        scoped = set(tenant_scoped_tables())
        keys = sql("""
            SELECT c.conrelid::regclass::text, c.confrelid::regclass::text,
                   array(SELECT attname FROM pg_attribute WHERE attrelid = c.conrelid AND attnum = ANY(c.conkey)
                         ORDER BY attname)
            FROM pg_constraint c WHERE c.contype = 'f'""")
        composite = {(t, p, tuple(a for a in cols if a != "tenant_id")) for t, p, cols in keys
                     if "tenant_id" in cols and len(cols) == 2}
        missing = [f"{t}.{cols[0]} -> {p}" for t, p, cols in keys
                   if t in scoped and p in scoped and cols != ["tenant_id"] and "tenant_id" not in cols
                   and (t, p, tuple(cols)) not in composite]
        self.assertEqual(missing, [])
        self.assertGreaterEqual(len(composite), 30)

    def test_every_plain_id_link_is_checked(self):
        found = set(sql("SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal"))
        self.assertEqual(PLAIN_ID_CHECKS - found, set())


class LinkedRowsProbeTests(TestCase):
    def setUp(self):
        self.a = Scenario("Tenant A", account="LA1")
        self.b = Scenario("Tenant B", account="LB1")
        bank.deposit("LB1", "1000", msisdn=self.b.m[3].msisdn, name="Member")
        bank.withdraw("LB1", "100", narration="Supplier")
        self.b.sync()
        self.b.approve("100")
        with self.b.acting():
            self.b_line = StatementLine.objects.filter(external_account_id=self.b.ea.id).first()
            self.b_entry = JournalEntry.objects.first()
            self.b_proposal_mandate = Mandate.objects.first()
        with self.a.acting():
            self.a_mandate_ref = self.a.approve("100")
            self.a_mandate = Mandate.objects.get(reference=self.a_mandate_ref)

    def modes(self):
        """Each write runs inside tenant A, then inside a cross-tenant
        operation where every row is visible, naming tenant A explicitly."""
        return [("inside tenant A", self.a.acting, {}),
                ("cross-tenant", lambda: cross_tenant("test: ADR-0017 probe", actor="test"),
                 {"tenant_id": self.a.tenant_id})]

    def refused(self, label, write):
        for mode, context, stamp in self.modes():
            with self.subTest(f"{label} ({mode})"), context():
                try:
                    with self.assertRaisesRegex(DatabaseError, REFUSED), transaction.atomic():
                        write(stamp)
                        with connection.cursor() as c:  # deferred keys are checked here, not at teardown
                            c.execute("SET CONSTRAINTS ALL IMMEDIATE")
                finally:
                    with connection.cursor() as c:  # the setting outlives the savepoint; restore it
                        c.execute("SET CONSTRAINTS ALL DEFERRED")

    def test_a_cross_context_key_cannot_name_another_tenants_row(self):
        b_member = self.b.m[3]
        self.refused("payer mapping naming B's group and member", lambda t: PayerMapping.objects.create(
            group_id=self.b.group.id, membership_id=b_member.id, msisdn=b_member.msisdn, confirmed_by="x", **t))
        self.refused("payer mapping in A's group naming B's member", lambda t: PayerMapping.objects.create(
            group_id=self.a.group.id, membership_id=b_member.id, msisdn=b_member.msisdn, confirmed_by="x", **t))
        self.refused("capability grant to B's member", lambda t: CapabilityChange.objects.create(
            group_id=self.a.group.id, membership_id=b_member.id, capability="correct_records", granted=True,
            changed_by="x", **t))

    def test_a_same_context_key_cannot_name_another_tenants_row(self):
        self.refused("vote in A on B's proposal", lambda t: Approval.objects.create(
            proposal_id=self.b_proposal_mandate.proposal_id, membership_id=self.a.m[0].id, approve=True, **t))
        self.refused("A's statement line on B's custodian account", lambda t: StatementLine.objects.create(
            external_account_id=self.b.ea.id, external_id="x", sequence=99, posted_at=timezone.now(),
            kind="deposit", amount=1, **t))

    def test_a_ledger_row_cannot_name_another_tenants_fund_member_or_account(self):
        def account(t, **kw):
            Account.objects.create(group_id=self.a.group.id, fund_id=self.a.fund.id, currency="KES", **kw, **t)

        self.refused("account naming B's fund", lambda t: Account.objects.create(
            group_id=self.b.group.id, fund_id=self.b.fund.id, purpose="retained", normal_side="C", **t))
        self.refused("A's account for B's member", lambda t: account(
            t, purpose="member_interest", normal_side="C", member_id=self.b.m[3].id))
        self.refused("A's cash account at B's custodian account", lambda t: account(
            t, purpose="custody_cash", normal_side="D", external_account_id=self.b.ea.id))

        def post_to_b(t):
            key = lambda p: AccountKey(group_id=self.b.group.id, fund_id=self.b.fund.id, purpose=p)
            post_journal(JournalDraft.build(
                idempotency_key="probe", group_id=self.b.group.id, fund_id=self.b.fund.id, kind="t", cause_type="t",
                cause_id="1", postings=[(key(AccountPurpose.UNEXPLAINED_OUT), Side.DEBIT, Money("5")),
                                        (key(AccountPurpose.RETAINED), Side.CREDIT, Money("5"))]))
        for mode, context, _ in self.modes()[:1]:  # posting needs a tenant to stamp
            with self.subTest(f"entry posted in A naming B's fund ({mode})"), context():
                with self.assertRaisesMessage(DatabaseError, "not its tenant"), transaction.atomic():
                    post_to_b({})

    def test_a_plain_id_from_custody_or_governance_cannot_name_another_tenants_row(self):
        with self.a.acting():
            a_line = StatementLine.objects.create(external_account_id=self.a.ea.id, external_id="own", sequence=50,
                                                  posted_at=timezone.now(), kind="deposit", amount=1)
        self.refused("A's resolution naming B's journal entry", lambda t: LineResolution.objects.create(
            line_id=a_line.id, outcome="unattributed", journal_entry_id=self.b_entry.id, **t))
        self.refused("A's mandate executed by B's line", lambda t: Mandate.objects.filter(
            pk=self.a_mandate.pk).update(executed_by_line_id=self.b_line.id))

    def test_the_rows_of_a_tenant_still_link_to_each_other(self):
        """The rule refuses only foreign links: the scenarios above posted,
        resolved, voted and issued mandates through the ordinary commands."""
        self.a.assert_sound(self)
        self.b.assert_sound(self)
