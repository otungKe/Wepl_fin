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

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Fund
from contexts.communities.public import (CommunityError, add_member, close_fund, create_group, fund_view, leave_group,
                                         members, membership, open_fund)
from contexts.governance.public import (Capability, GovernanceError, adopt_constitution, grant, proposal_view,
                                        propose_withdrawal)
from contexts.tenancy.public import tenant

JOINERS = 8


class ConcurrentJoinTests(unittest.TestCase):
    databases = {"default"}  # so the runner builds the test database even when run alone
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

    def test_leaving_twice_at_once_ends_the_spell_once(self):
        group = create_group("Concurrent leave", actor="test")
        with tenant(group.tenant_id):
            m = add_member(group.id, msisdn="0798000002", name="Leaver", actor="test")
        errors = run_together(lambda n: leave_group(m.id, actor="test"), group.tenant_id)
        self.assertEqual(len(errors), JOINERS - 1)
        self.assertTrue(all(isinstance(e, CommunityError) for e in errors), errors)
        with tenant(group.tenant_id):
            self.assertEqual(membership(m.id).status, "left")
            left_events = [e for e in history(target_type="membership", target_id=m.id) if e["action"] == "member.left"]
        self.assertEqual(len(left_events), 1)


class ConcurrentFundTests(unittest.TestCase):
    """The unique (group, name) constraint decides, not an earlier check."""
    databases = {"default"}  # so the runner builds the test database even when run alone

    def test_the_same_name_opened_at_once_gives_one_fund(self):
        group = create_group("Concurrent funds", actor="test")
        errors = run_together(lambda n: open_fund(group.id, name="Welfare", actor="test"), group.tenant_id)
        self.assertEqual(len(errors), JOINERS - 1)
        self.assertTrue(all(isinstance(e, CommunityError) and "already has" in str(e) for e in errors), errors)
        with tenant(group.tenant_id):
            self.assertEqual(Fund.objects.filter(group_id=group.id).count(), 1)

    def test_different_names_opened_at_once_all_succeed(self):
        group = create_group("Concurrent fund names", actor="test")
        errors = run_together(lambda n: open_fund(group.id, name=f"Fund {n}", actor="test"), group.tenant_id)
        self.assertEqual(errors, [])
        with tenant(group.tenant_id):
            self.assertEqual(Fund.objects.filter(group_id=group.id).count(), JOINERS)


class ClosingWhileProposingTests(unittest.TestCase):
    """Closing a fund and proposing on it serialise on the fund row (ADR-0015):
    never a closed fund with an open proposal."""
    databases = {"default"}  # so the runner builds the test database even when run alone

    def test_a_fund_never_closes_under_an_open_proposal(self):
        from tests.scenario import RULES
        group = create_group("Close while proposing", actor="test")
        with tenant(group.tenant_id):
            fund = open_fund(group.id, name="Welfare", actor="test")
            adopt_constitution(group.id, RULES, actor="test")
            people = [add_member(group.id, msisdn=f"07970000{n:02d}", name=f"P{n}", actor="test") for n in range(3)]
            for p in people[1:]:
                grant(p.id, Capability.APPROVE_PAYOUT, actor="test")
        proposed = []

        def act(n):
            if n == JOINERS // 2:
                close_fund(fund.id, actor="test")
            else:
                proposed.append(propose_withdrawal(people[0].id, fund.id, amount="10", purpose=f"x{n}",
                                                   payee_name="x", payee_account="0799000000").id)

        errors = run_together(act, group.tenant_id)
        self.assertTrue(all(isinstance(e, (CommunityError, GovernanceError)) for e in errors), errors)
        with tenant(group.tenant_id):
            if not fund_view(fund.id).is_open:
                self.assertEqual([p for p in proposed if proposal_view(p).status == "open"], [])
            else:
                self.assertTrue(proposed)


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
