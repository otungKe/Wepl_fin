"""Tenant isolation enforced by PostgreSQL row-level security (ADR-0009,
foundational decisions 2–8). These tests go around the application on
purpose, with raw SQL and the ORM, to show the database itself refuses."""
from unittest import mock

from django.apps import apps
from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from contexts.audit.infrastructure.models import AuditEvent
from contexts.communities.public import CommunityError, create_group, group_view
from contexts.custody.infrastructure.models import StatementLine
from contexts.custody.public import CustodyError, attribute_payment
from contexts.governance.infrastructure.models import Mandate
from contexts.ledger.infrastructure.models import JournalEntry
from contexts.ledger.public import member_balances
from contexts.tenancy.contract import TenantScope
from contexts.tenancy.infrastructure.session import database_tenant, role_bypasses_rls
from contexts.tenancy.public import TenancyError, cross_tenant, current_tenant, provision_tenant, tenant
from simulators.im_bank import bank
from tests.scenario import SIGNATORY, Scenario

OURS = {"audit", "tenancy", "identity", "communities", "governance", "ledger", "custody", "notifications", "simulator"}


def tenant_scoped_tables() -> list[str]:
    return [m._meta.db_table for m in apps.get_models()
            if m._meta.app_label in OURS and m.tenant_scope == TenantScope.TENANT_SCOPED]


def sql(query, params=()):
    with connection.cursor() as c:
        c.execute(query, params)
        return c.fetchall() if c.description else c.rowcount


class RlsIsolationTests(TestCase):
    def setUp(self):
        self.a = Scenario("Tenant A", account="A1")
        self.b = Scenario("Tenant B", account="B1", people=[("0722000001", "B1", "Chair", SIGNATORY),
                                                           ("0722000002", "B2", "Treasurer", SIGNATORY),
                                                           ("0722000003", "B3", "Secretary", SIGNATORY)])
        for s, acct in ((self.a, "A1"), (self.b, "B1")):
            for m in s.m:
                bank.deposit(acct, "1000", msisdn=m.msisdn, name="X")
            bank.deposit(acct, "50", msisdn="0733000000", name="STRANGER")
            s.sync()
        self.b_ref = self.b.approve("100")

    def test_every_tenant_table_shows_only_the_current_tenants_rows(self):
        for table in tenant_scoped_tables():
            with self.subTest(table):
                with self.a.acting():
                    seen = {t for (t,) in sql(f"SELECT DISTINCT tenant_id FROM {table}")}
                self.assertLessEqual(seen, {self.a.tenant_id})
        with self.b.acting():
            self.assertTrue(sql("SELECT count(*) FROM ledger_journalentry")[0][0] > 0)

    def test_nothing_is_visible_or_writable_without_a_tenant(self):
        for table in tenant_scoped_tables():
            with self.subTest(table):
                self.assertEqual(sql(f"SELECT count(*) FROM {table}")[0][0], 0)
        with self.assertRaises(DatabaseError), transaction.atomic():
            sql("INSERT INTO communities_group (name, created_at) VALUES ('x', now())")

    def test_raw_sql_cannot_read_change_or_delete_another_tenants_rows(self):
        with self.b.acting():
            b_line = StatementLine.objects.filter(amount=50).get().pk
        with self.a.acting():
            self.assertEqual(sql("SELECT count(*) FROM custody_statementline WHERE id = %s", [b_line])[0][0], 0)
            self.assertEqual(sql("UPDATE governance_mandate SET status = 'expired' WHERE reference = %s",
                                 [self.b_ref]), 0)
            self.assertEqual(sql("DELETE FROM notifications_outboxevent WHERE tenant_id = %s", [self.b.tenant_id]), 0)
        with self.b.acting():
            self.assertEqual(Mandate.objects.get(reference=self.b_ref).status, "issued")

    def test_a_row_cannot_be_written_into_another_tenant(self):
        with self.a.acting(), self.assertRaisesMessage(DatabaseError, "row-level security"), transaction.atomic():
            sql("INSERT INTO communities_group (tenant_id, name, created_at) VALUES (%s, 'x', now())",
                [self.b.tenant_id])
        with self.a.acting(), self.assertRaisesMessage(DatabaseError, "row-level security"), transaction.atomic():
            sql("UPDATE communities_membership SET tenant_id = %s", [self.b.tenant_id])

    def test_a_command_given_another_tenants_ids_fails_and_writes_nothing(self):
        with self.b.acting():
            b_line = StatementLine.objects.get(amount=50).pk
        with self.a.acting():
            before = JournalEntry.objects.count()
            with self.assertRaises((StatementLine.DoesNotExist, CustodyError)):
                attribute_payment(b_line, self.a.m[3].id, by=self.a.m[0].id)
            a_line = StatementLine.objects.get(amount=50).pk
            with self.assertRaisesMessage(CustodyError, "not in this group"):
                attribute_payment(a_line, self.b.m[0].id, by=self.a.m[0].id)
            with self.assertRaisesMessage(CustodyError, "unknown member"):
                attribute_payment(a_line, self.a.m[3].id, by=self.b.m[0].id)
            self.assertEqual(JournalEntry.objects.count(), before)
            self.assertNotIn(self.b.m[0].id, member_balances(self.b.fund.id))  # B's books read as empty

    def test_cross_tenant_access_is_declared_and_audited(self):
        with cross_tenant("support investigation #12", actor="ops:harry"):
            tenants = {t for (t,) in sql("SELECT DISTINCT tenant_id FROM ledger_journalentry")}
            self.assertEqual(tenants, {self.a.tenant_id, self.b.tenant_id})
            event = AuditEvent.objects.filter(action="tenancy.cross_tenant").latest("id")
        self.assertEqual((event.actor, event.data["reason"]), ("ops:harry", "support investigation #12"))
        with self.assertRaisesMessage(TenancyError, "must say why"), cross_tenant("", actor="x"):
            pass

    def test_switching_tenant_mid_operation_is_refused(self):
        with self.a.acting():
            with self.assertRaisesMessage(TenancyError, "cannot switch"), self.b.acting():
                pass
            with self.assertRaisesMessage(TenancyError, "cross-tenant"), cross_tenant("x", actor="y"):
                pass
        with cross_tenant("x", actor="y"), self.assertRaisesMessage(TenancyError, "inside a cross-tenant"):
            with self.a.acting():
                pass

    def test_context_is_cleared_after_each_block_and_after_a_failure(self):
        """Decision 7: a worker never reuses the previous task's tenant."""
        with self.a.acting():
            self.assertEqual((current_tenant(), database_tenant()), (self.a.tenant_id, self.a.tenant_id))
        self.assertEqual((current_tenant(), database_tenant()), (None, None))
        with self.assertRaises(ZeroDivisionError), self.b.acting():
            1 / 0
        self.assertEqual((current_tenant(), database_tenant()), (None, None))
        with self.assertRaisesMessage(TenancyError, "Unknown tenant"), tenant(999999):
            pass


class GroupIsTenantTests(TestCase):
    """ADR-0010: each group is its own tenant, never a partition inside one."""

    def test_a_tenant_holds_exactly_one_group(self):
        s = Scenario()
        with s.acting():
            with self.assertRaisesMessage(CommunityError, "outside any tenant"):
                create_group("Second group", actor="test")
            with self.assertRaisesMessage(DatabaseError, "community_one_group_per_tenant"), transaction.atomic():
                sql("INSERT INTO communities_group (name, created_at) VALUES ('x', now())")

    def test_founding_a_group_establishes_its_own_tenant(self):
        """ADR-0013: not "enter a tenant, then create a group inside it"."""
        group = create_group("Founded", actor="test")
        self.assertIsNotNone(group.tenant_id)
        self.assertIsNone(current_tenant())
        with tenant(group.tenant_id):
            self.assertEqual(group_view(group.id).tenant_id, group.tenant_id)
        self.assertNotEqual(create_group("Another", actor="test").tenant_id, group.tenant_id)

    def test_a_tenant_without_its_group_cannot_commit(self):
        """Provisioning a bare tenant, the "tenant containing a group" shape,
        is refused by the database when the transaction commits."""
        provision_tenant("Bare", actor="test")
        with self.assertRaisesMessage(DatabaseError, "has no group"), connection.cursor() as c:
            c.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_a_failed_founding_leaves_no_tenant_behind(self):
        with cross_tenant("count tenants", actor="test"):
            before = sql("SELECT count(*) FROM tenancy_tenant")[0][0]
        with mock.patch("contexts.communities.application.groups.record", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                create_group("Doomed", actor="test")
        with cross_tenant("count tenants", actor="test"):
            self.assertEqual(sql("SELECT count(*) FROM tenancy_tenant")[0][0], before)


class DatabaseShapeTests(TestCase):
    def test_the_application_role_cannot_bypass_row_level_security(self):
        self.assertFalse(role_bypasses_rls(), "tests must run as a role like wepl_app, not a superuser")

    def test_every_model_declares_its_tenant_scope(self):
        missing = [f"{m._meta.label}" for m in apps.get_models()
                   if m._meta.app_label in OURS and not isinstance(getattr(m, "tenant_scope", None), TenantScope)]
        self.assertEqual(missing, [])

    def test_every_tenant_scoped_table_forces_rls_with_a_policy_and_a_tenant(self):
        problems = []
        for table in tenant_scoped_tables():
            enabled, forced = sql("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                                  [table])[0]
            policies = sql("SELECT count(*) FROM pg_policies WHERE tablename = %s", [table])[0][0]
            nullable = sql("SELECT is_nullable FROM information_schema.columns WHERE table_name = %s "
                           "AND column_name = 'tenant_id'", [table])
            if not (enabled and forced and policies):
                problems.append(f"{table}: rls={enabled} forced={forced} policies={policies}")
            if not nullable or (nullable[0][0] == "YES" and table != "audit_auditevent"):
                problems.append(f"{table}: tenant_id missing or nullable")
        self.assertEqual(problems, [])

    def test_no_other_table_has_a_tenant_column_without_rls(self):
        scoped = set(tenant_scoped_tables())
        with_column = {t for (t,) in sql("SELECT table_name FROM information_schema.columns "
                                         "WHERE column_name = 'tenant_id' AND table_schema = 'public'")}
        self.assertEqual(with_column - scoped, set())
