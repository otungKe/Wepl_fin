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

from contexts.communities.public import CommunityError, add_member, create_group, members
from contexts.tenancy.public import tenant

JOINERS = 8


class ConcurrentJoinTests(unittest.TestCase):
    def test_simultaneous_joins_never_share_a_code(self):
        group = create_group("Concurrency", actor="test")
        errors = run_together(lambda n: add_member(group.id, msisdn=f"0799{n:06d}", name=f"J{n}", actor="test"),
                              group.tenant_id)
        self.assertEqual(errors, [])
        with tenant(group.tenant_id):
            codes = sorted(m.code for m in members(group.id))
        self.assertEqual(codes, [f"M{n:02d}" for n in range(1, JOINERS + 1)])

    def test_the_same_person_joining_twice_at_once_gets_one_membership(self):
        group = create_group("Concurrent rejoin", actor="test")
        errors = run_together(lambda n: add_member(group.id, msisdn="0798000001", name="Same", actor="test"),
                              group.tenant_id)
        self.assertEqual(len(errors), JOINERS - 1)
        self.assertTrue(all(isinstance(e, CommunityError) for e in errors), errors)
        with tenant(group.tenant_id):
            self.assertEqual([m.code for m in members(group.id)], ["M01"])


def run_together(action, tenant_id) -> list[Exception]:
    """Run ``action(n)`` on JOINERS threads, released at the same instant,
    each on its own connection in its own transaction."""
    start, errors = threading.Barrier(JOINERS), []

    def run(n):
        try:
            start.wait()
            with tenant(tenant_id):
                action(n)
        except Exception as exc:  # reported by the caller, with every other thread's outcome
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(n,)) for n in range(JOINERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors
