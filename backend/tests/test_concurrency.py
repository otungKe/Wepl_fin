"""Concurrent joins get distinct member codes (ADR-0012).

This needs real, committed transactions on separate connections, which
Django's TestCase cannot give and TransactionTestCase cannot clean up (its
flush truncates tables whose triggers refuse it). So this is a plain
unittest.TestCase: its rows are committed in a tenant of its own, invisible
to every other tenant, and Django runs such tests after all its own test
cases. The test database is destroyed at the end of the run."""
import threading
import unittest

from django.db import connection

from contexts.communities.public import add_member, create_group, members
from contexts.tenancy.public import provision_tenant, tenant

JOINERS = 8


class ConcurrentJoinTests(unittest.TestCase):
    def test_simultaneous_joins_never_share_a_code(self):
        tenant_id = provision_tenant("Concurrency", actor="test").id
        with tenant(tenant_id):
            group, _ = create_group("Concurrency", actor="test")
        start, errors = threading.Barrier(JOINERS), []

        def join(n):
            try:
                start.wait()
                with tenant(tenant_id):
                    add_member(group.id, msisdn=f"0799{n:06d}", name=f"J{n}", actor="test")
            except Exception as exc:  # reported below, with every other thread's outcome
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=join, args=(n,)) for n in range(JOINERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        with tenant(tenant_id):
            codes = sorted(m.code for m in members(group.id))
        self.assertEqual(codes, [f"M{n:02d}" for n in range(1, JOINERS + 1)])
