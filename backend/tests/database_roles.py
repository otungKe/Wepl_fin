"""Tests run as the application's role (ADR-0027).

The test database is created and migrated by the schema owner, as in
deployment, and every test then connects as the application's role, which
owns nothing. A test that must do what only the owner can (turn a rule off,
or run migration SQL) says so with ``AsSchemaOwner``."""
from contextlib import contextmanager

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import TestCase
from django.test.runner import DiscoverRunner


def _owner_login() -> dict:
    owner = connections.settings.get("owner")
    if owner is None:
        raise ImproperlyConfigured("Tests need the schema owner's login: set DB_OWNER_USER and DB_OWNER_PASSWORD "
                                   "(README, ADR-0027).")
    return {"USER": owner["USER"], "PASSWORD": owner["PASSWORD"]}


@contextmanager
def schema_owner():
    """Connect the default alias as the schema owner for the block. Not for
    use inside a test's transaction: the connection is closed and reopened."""
    default = connections["default"]
    runtime = {"USER": default.settings_dict["USER"], "PASSWORD": default.settings_dict["PASSWORD"]}
    default.close()
    default.settings_dict.update(_owner_login())
    try:
        yield
    finally:
        default.close()
        default.settings_dict.update(runtime)


class RuntimeRoleRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        with schema_owner():
            config = super().setup_databases(**kwargs)
        # The owner alias always points at the test database, never the real one.
        connections["owner"].close()
        connections["owner"].settings_dict["NAME"] = connections["default"].settings_dict["NAME"]
        return config

    def run_checks(self, databases):
        # The owner alias is the schema owner by design; its warning is noise here.
        super().run_checks([alias for alias in databases if alias != "owner"])

    def teardown_databases(self, old_config, **kwargs):
        connections["owner"].close()
        with schema_owner():
            super().teardown_databases(old_config, **kwargs)


class AsSchemaOwner(TestCase):
    """A test case whose every test connects as the schema owner: for tests
    that turn a database rule off, as only the owner, a superuser or a
    restore could, or that run migration SQL. Everything else in it behaves
    as for the application: the owner is bound by row-level security too."""

    @classmethod
    def setUpClass(cls):
        cls._owner = schema_owner()
        cls._owner.__enter__()
        cls.addClassCleanup(cls._owner.__exit__, None, None, None)
        super().setUpClass()
