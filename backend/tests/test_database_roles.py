"""ADR-0027: the application does not own its tables.

The application's role can read and insert, update rows whose state may
change, and nothing else: it cannot turn a rule off, edit history, delete,
or become the owner. The append-only triggers stay as a second lock, which
holds even for the owner."""
from django.db import DatabaseError, connections, transaction
from django.test import TestCase

from contexts.tenancy.infrastructure.checks import database_role_owns_nothing
from contexts.tenancy.infrastructure.session import role_privilege_problems
from contexts.tenancy.public import cross_tenant
from simulators.custodian_bank import bank
from tests.database_roles import AsSchemaOwner
from tests.scenario import Scenario

INSUFFICIENT_PRIVILEGE = "42501"


def sql(query, params=(), using="default"):
    with connections[using].cursor() as c:
        c.execute(query, params)
        return c.fetchall() if c.description else None


def append_only_tables():
    return [t for (t,) in sql("""SELECT DISTINCT t.tgrelid::regclass::text FROM pg_trigger t
                                   JOIN pg_proc p ON p.oid = t.tgfoid
                                  WHERE p.proname LIKE '%%\\_append\\_only' AND NOT t.tgisinternal ORDER BY 1""")]


class TheApplicationsRoleTests(TestCase):
    def refused(self, statement):
        """Refused for want of privilege, before any trigger or policy runs."""
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            sql(statement)
        self.assertEqual(caught.exception.__cause__.sqlstate, INSUFFICIENT_PRIVILEGE, caught.exception)

    def test_it_is_the_runtime_role_and_owns_nothing(self):
        self.assertEqual(sql("""SELECT current_user, pg_has_role(current_user, 'wepl_runtime', 'MEMBER'),
                                       pg_has_role(current_user, 'wepl_owner', 'MEMBER')""")[0],
                         ("wepl_app", True, False))
        self.assertEqual(role_privilege_problems(), [])
        self.assertEqual(database_role_owns_nothing(None, databases=["default"]), [])

    def test_it_cannot_turn_a_rule_off(self):
        for statement in ("ALTER TABLE ledger_journalline DISABLE TRIGGER ledger_journalline_append_only_row",
                          "ALTER TABLE ledger_journalline DISABLE TRIGGER ALL",
                          "DROP TRIGGER ledger_line_balanced ON ledger_journalline",
                          "DROP POLICY ledger_journalline_tenant_isolation ON ledger_journalline",
                          "ALTER TABLE ledger_journalline NO FORCE ROW LEVEL SECURITY",
                          "ALTER TABLE ledger_account DROP CONSTRAINT ledger_account_id_tenant",
                          "CREATE TRIGGER sneak BEFORE INSERT ON ledger_journalline "
                          "FOR EACH ROW EXECUTE FUNCTION wepl_stamp_tenant()",
                          "CREATE OR REPLACE FUNCTION wepl_cross_tenant() RETURNS boolean LANGUAGE sql AS 'SELECT true'",
                          "CREATE TABLE sneak (id int)",
                          "SET ROLE wepl_owner"):
            with self.subTest(statement):
                self.refused(statement)

    def test_it_cannot_edit_or_delete_history(self):
        for table in append_only_tables():
            for statement in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"):
                with self.subTest(statement):
                    self.refused(statement)

    def test_it_deletes_nothing_anywhere(self):
        tables = [t for (t,) in sql("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")]
        self.assertGreater(len(tables), 30)
        for table in tables:
            with self.subTest(table):
                self.refused(f"DELETE FROM {table}")

    def test_it_updates_where_state_changes_but_not_the_migration_history(self):
        self.assertEqual(sql("""SELECT has_table_privilege('governance_proposal', 'UPDATE'),
                                       has_table_privilege('communities_fund', 'UPDATE'),
                                       has_table_privilege('django_migrations', 'SELECT'),
                                       has_table_privilege('django_migrations', 'INSERT, UPDATE')""")[0],
                         (True, True, True, False))


class TheBootCheckTests(TestCase):
    """tenancy.E002 sees what would let a role turn a rule off. Each case is
    set up on the owner's connection and rolled back with the test."""
    databases = {"default", "owner"}

    def test_it_names_an_update_granted_on_an_append_only_table(self):
        sql("GRANT UPDATE ON ledger_journalline TO wepl_runtime", using="owner")
        self.assertEqual(role_privilege_problems("owner", role="wepl_app"),
                         ["can UPDATE append-only ledger_journalline"])

    def test_it_names_a_delete_anywhere_and_create_in_the_schema(self):
        sql("GRANT DELETE ON notifications_outboxevent TO wepl_runtime", using="owner")
        sql("GRANT CREATE ON SCHEMA public TO wepl_runtime", using="owner")
        self.assertEqual(role_privilege_problems("owner", role="wepl_app"),
                         ["can DELETE, TRUNCATE, REFERENCES or TRIGGER notifications_outboxevent",
                          "can CREATE in schema public"])

    def test_it_names_a_role_that_owns_the_tables(self):
        """As wepl_app did before ADR-0027 (review 2026-10-06, H1)."""
        [problem, *_] = role_privilege_problems("owner", role="wepl_owner")
        self.assertTrue(problem.startswith("owns "), problem)

    def test_the_owner_is_only_warned_so_migrate_can_run(self):
        [found] = database_role_owns_nothing(None, databases=["owner"])
        self.assertEqual((found.id, found.is_serious()), ("tenancy.W001", False))


class HistoryHoldsEvenForTheOwnerTests(AsSchemaOwner):
    """The second lock: the owner has every privilege on its tables, and the
    append-only triggers still refuse it. (Only by turning a trigger off,
    which the application's role cannot, does the owner get past them.)"""

    def setUp(self):
        self.assertEqual(sql("SELECT current_user")[0][0], "wepl_owner")
        s = Scenario("Owner", account="OWN1")
        for m in s.m:
            bank.deposit("OWN1", "100", msisdn=m.msisdn, name="X")
        s.sync()
        s.approve("50")

    def refused_by_a_trigger(self, statement):
        with self.assertRaises(DatabaseError) as caught, transaction.atomic():
            sql(statement)
        self.assertNotEqual(caught.exception.__cause__.sqlstate, INSUFFICIENT_PRIVILEGE, caught.exception)

    def test_append_only_tables_refuse_the_owner(self):
        tables = append_only_tables()
        self.assertGreaterEqual(len(tables), 15)
        sql("SET CONSTRAINTS ALL IMMEDIATE")  # TRUNCATE refuses while trigger events are pending
        self.addCleanup(sql, "SET CONSTRAINTS ALL DEFERRED")  # it would outlive the test's savepoint
        with cross_tenant("test: every row", actor="test"):
            for table in tables:
                rows = sql(f"SELECT count(*) FROM {table}")[0][0]
                statements = [f"TRUNCATE {table} CASCADE"]
                if rows:  # a row trigger fires only for a row
                    statements += [f"UPDATE {table} SET id = id", f"DELETE FROM {table}"]
                for statement in statements:
                    with self.subTest(statement):
                        self.refused_by_a_trigger(statement)
        self.assertEqual(
            sql("""SELECT count(DISTINCT t.tgrelid) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
                    WHERE p.proname LIKE '%%\\_append\\_only' AND NOT t.tgisinternal AND t.tgenabled = 'O'
                      AND t.tgtype & 1 = 1 AND t.tgtype & 2 = 2 AND t.tgtype & 8 = 8 AND t.tgtype & 16 = 16"""),
            [(len(tables),)])  # each has an enabled row trigger, BEFORE UPDATE and DELETE

    def test_funds_are_never_deleted_even_by_the_owner(self):
        with cross_tenant("test: every row", actor="test"):
            self.refused_by_a_trigger("DELETE FROM communities_fund")
