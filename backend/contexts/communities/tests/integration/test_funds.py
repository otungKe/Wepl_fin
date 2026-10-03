"""Opening a fund: a group's named pool of money, nothing more
(ADR-0013; docs/architecture/review-funds-module.md)."""
from unittest import mock

from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase

from contexts.audit.public import history
from contexts.communities.infrastructure.models import Fund
from contexts.communities.public import (CommunityError, add_member, close_fund, create_group, fund_view, open_fund,
                                         rename_fund)
from contexts.custody.public import CustodyError, link_external_account
from contexts.governance.public import Capability, GovernanceError, grant, adopt_constitution, cancel_proposal, propose_withdrawal
from contexts.ledger.public import (AccountKey, AccountPurpose, JournalDraft, Side, fund_holds_nothing, post_journal,
                                    reverse_journal)
from contexts.shared_kernel.money import Money
from contexts.custody.infrastructure.models import ExternalAccount
from contexts.ledger.infrastructure.models import Account, JournalEntry
from contexts.notifications.infrastructure.models import OutboxEvent
from contexts.tenancy.public import TenancyError, cross_tenant, tenant


class OpeningTests(TestCase):
    def setUp(self):
        self.a = create_group("A", actor="t")
        self.b = create_group("B", actor="t")
        with tenant(self.b.tenant_id):
            self.b_fund = open_fund(self.b.id, name="Savings", actor="t")
        self.enterContext(tenant(self.a.tenant_id))

    def test_a_fund_is_opened_and_audited(self):
        f = open_fund(self.a.id, name="  Main   savings ", currency="KES", actor="0712000001")
        self.assertEqual((f.group_id, f.name, f.currency), (self.a.id, "Main savings", "KES"))
        [event] = history(target_type="fund", target_id=f.id)
        self.assertEqual((event["actor"], event["action"], event["data"]),
                         ("0712000001", "fund.opened", {"name": "Main savings", "currency": "KES"}))

    def test_the_group_names_its_fund_and_it_is_held_in_kes(self):
        with self.assertRaises(TypeError):  # no default name: the constitution names each fund (§3)
            open_fund(self.a.id, actor="t")
        self.assertEqual(open_fund(self.a.id, name="Welfare", actor="t").currency, "KES")

    def test_only_kes_for_the_pilot(self):
        with self.assertRaisesMessage(CommunityError, "KES only"):
            open_fund(self.a.id, name="Dollars", currency="USD", actor="t")
        with self.assertRaisesMessage(DatabaseError, "community_fund_currency"), transaction.atomic():
            Fund.objects.create(group_id=self.a.id, name="Dollars", currency="USD")

    def test_invalid_names_and_currencies_are_community_errors(self):
        for kw in ({"name": None}, {"name": "  "}, {"name": "x" * 81}, {"currency": "kes"}, {"currency": ""},
                   {"currency": "USDX"}):
            with self.subTest(kw), self.assertRaises(CommunityError):
                open_fund(self.a.id, actor="t", **{"name": "Valid", **kw})
        self.assertFalse(Fund.objects.exists())

    def test_names_are_unique_per_group_only(self):
        open_fund(self.a.id, name="Savings", actor="t")  # B has one too
        open_fund(self.a.id, name="Welfare", actor="t")
        with self.assertRaisesMessage(CommunityError, "A already has a fund called 'Savings'"):
            open_fund(self.a.id, name=" Savings", actor="t")
        for variant in ("savings", "SAVINGS"):  # one fund to members, whatever the case (Harry, 2026-10-01)
            with self.subTest(variant), self.assertRaisesMessage(CommunityError, "already has a fund"):
                open_fund(self.a.id, name=variant, actor="t")
        with self.assertRaisesMessage(DatabaseError, "community_open_fund_name_any_case"), transaction.atomic():
            Fund.objects.create(group_id=self.a.id, name="WELFARE")

    def test_a_failed_audit_leaves_no_fund(self):
        with mock.patch("contexts.communities.application.funds.record", side_effect=RuntimeError("audit down")):
            with self.assertRaises(RuntimeError):
                open_fund(self.a.id, name="Audited", actor="t")
        self.assertFalse(Fund.objects.filter(name="Audited").exists())

    def test_another_integrity_failure_is_not_reported_as_a_duplicate(self):
        refusal = IntegrityError("some other rule")
        with mock.patch.object(Fund.objects, "create", side_effect=refusal):
            with self.assertRaisesMessage(IntegrityError, "some other rule"):
                open_fund(self.a.id, name="Other", actor="t")

    def test_opening_a_fund_moves_no_money(self):
        tables = (Account, JournalEntry, ExternalAccount, OutboxEvent)
        before = {t.__name__: t.objects.count() for t in tables}
        open_fund(self.a.id, name="Welfare", actor="t")
        self.assertEqual({t.__name__: t.objects.count() for t in tables}, before)


class FundTenantTests(TestCase):
    """A fund lives in its group's tenant, whoever writes it (review B1, B3, B4)."""

    def setUp(self):
        self.a = create_group("A", actor="t")
        self.b = create_group("B", actor="t")
        with tenant(self.b.tenant_id):
            self.b_fund = open_fund(self.b.id, name="Savings", actor="t")

    def test_a_foreign_or_unknown_group_is_refused_and_nothing_is_written(self):
        with tenant(self.a.tenant_id):
            for group_id in (self.b.id, 999999):
                with self.subTest(group_id), self.assertRaisesMessage(CommunityError, "Unknown group"):
                    open_fund(group_id, name="Stolen", actor="t")
        with cross_tenant("test: count every fund", actor="t"):
            self.assertEqual(Fund.objects.count(), 1)

    def test_a_foreign_or_unknown_fund_is_a_community_error(self):
        with tenant(self.a.tenant_id):
            for fund_id in (self.b_fund.id, 999999):
                with self.subTest(fund_id), self.assertRaisesMessage(CommunityError, "Unknown fund"):
                    fund_view(fund_id)

    def test_no_tenant_context_is_a_tenancy_error(self):
        with self.assertRaisesMessage(TenancyError, "needs a tenant context"):
            open_fund(self.a.id, name="Savings", actor="t")
        with cross_tenant("test: every group visible, no tenant", actor="t"):
            with self.assertRaisesMessage(TenancyError, "needs a tenant context"):
                open_fund(self.a.id, name="Savings", actor="t")  # was misreported as "already has a fund"

    def test_the_database_refuses_a_fund_for_a_foreign_group(self):
        with tenant(self.a.tenant_id), self.assertRaisesMessage(DatabaseError, "unknown group"), \
                transaction.atomic():
            Fund.objects.create(group_id=self.b.id, name="Stolen")

    def test_the_database_refuses_a_fund_outside_its_groups_tenant(self):
        with cross_tenant("test: write across tenants", actor="t"):
            with self.assertRaisesMessage(DatabaseError, "belongs to its group's tenant"), transaction.atomic():
                Fund.objects.create(group_id=self.b.id, name="Mismatch", tenant_id=self.a.tenant_id)
            self.assertEqual(Fund.objects.create(group_id=self.b.id, name="Right", tenant_id=self.b.tenant_id)
                             .group_id, self.b.id)

    def test_a_funds_group_and_currency_never_change(self):
        with tenant(self.b.tenant_id):
            for change in ({"currency": "USD"}, {"group_id": self.a.id}):
                with self.subTest(change), self.assertRaisesMessage(DatabaseError, "never change"), transaction.atomic():
                    Fund.objects.filter(pk=self.b_fund.id).update(**change)
            Fund.objects.filter(pk=self.b_fund.id).update(name="Main savings")  # renaming is review D2: not ruled
            self.assertEqual((fund_view(self.b_fund.id).currency, fund_view(self.b_fund.id).group_id),
                             ("KES", self.b.id))


class LifecycleTests(TestCase):
    """Open, rename while open, close when empty; never reopened or deleted (ADR-0015)."""

    def setUp(self):
        self.group = create_group("G", actor="t")
        self.enterContext(tenant(self.group.tenant_id))
        self.fund = open_fund(self.group.id, name="Welfare", actor="t")

    def test_an_open_fund_is_renamed_and_the_old_name_kept_in_the_audit(self):
        open_fund(self.group.id, name="Savings", actor="t")
        f = rename_fund(self.fund.id, "  Welfare   kitty ", actor="0712000001")
        self.assertEqual(f.name, "Welfare kitty")
        self.assertEqual(rename_fund(self.fund.id, "WELFARE KITTY", actor="t").name, "WELFARE KITTY")  # its own name
        with self.assertRaisesMessage(CommunityError, "already has a fund called 'savings'"):
            rename_fund(self.fund.id, "savings", actor="t")
        renames = [e["data"] for e in history(target_type="fund", target_id=self.fund.id)
                   if e["action"] == "fund.renamed"]
        self.assertEqual(renames, [{"from": "Welfare", "to": "Welfare kitty"},
                                   {"from": "Welfare kitty", "to": "WELFARE KITTY"}])

    def test_an_empty_fund_closes_for_good(self):
        f = close_fund(self.fund.id, actor="t")
        self.assertEqual((f.status, f.is_open), ("closed", False))
        self.assertIn("fund.closed", [e["action"] for e in history(target_type="fund", target_id=f.id)])
        for use_case in (lambda: close_fund(f.id, actor="t"), lambda: rename_fund(f.id, "Other", actor="t")):
            with self.subTest(use_case), self.assertRaisesMessage(CommunityError, "closed"):
                use_case()
        for change in ({"status": "open"}, {"name": "Other"}):
            with self.subTest(change), self.assertRaisesMessage(DatabaseError, "never reopens"), \
                    transaction.atomic():
                Fund.objects.filter(pk=f.id).update(**change)

    def test_a_closed_funds_name_is_free_again(self):
        close_fund(self.fund.id, actor="t")
        again = open_fund(self.group.id, name="welfare", actor="t")
        self.assertNotEqual(again.id, self.fund.id)
        self.assertEqual(fund_view(self.fund.id).name, "Welfare")  # the old fund still means the old pool

    def test_funds_are_never_deleted(self):
        for fund in (self.fund, close_fund(open_fund(self.group.id, name="Old", actor="t").id, actor="t")):
            with self.subTest(fund.status), self.assertRaisesMessage(DatabaseError, "never deleted"), \
                    transaction.atomic():
                Fund.objects.filter(pk=fund.id).delete()

    def test_a_fund_holding_money_does_not_close_until_it_is_empty(self):
        key = lambda purpose, **kw: AccountKey(group_id=self.group.id, fund_id=self.fund.id, purpose=purpose, **kw)
        entry = post_journal(JournalDraft.build(
            idempotency_key="t-1", group_id=self.group.id, fund_id=self.fund.id, kind="test", cause_type="test",
            cause_id="1", postings=[(key(AccountPurpose.UNEXPLAINED_OUT), Side.DEBIT, Money("100")),
                                    (key(AccountPurpose.RETAINED), Side.CREDIT, Money("100"))]))
        self.assertFalse(fund_holds_nothing(self.fund.id))
        with self.assertRaisesMessage(CommunityError, "still holds money"):
            close_fund(self.fund.id, actor="t")
        reverse_journal(entry, idempotency_key="t-1-reversal")
        self.assertTrue(fund_holds_nothing(self.fund.id))
        self.assertEqual(close_fund(self.fund.id, actor="t").status, "closed")


class OtherContextsAndAClosedFundTests(TestCase):
    """Governance and custody each refuse what is theirs (ADR-0015)."""

    def test_a_fund_with_an_open_proposal_does_not_close_and_a_closed_fund_takes_none(self):
        from tests.scenario import RULES
        group = create_group("G", actor="t")
        self.enterContext(tenant(group.tenant_id))
        fund, spare = (open_fund(group.id, name=n, actor="t") for n in ("Welfare", "Spare"))
        adopt_constitution(group.id, RULES, actor="t")
        m, *approvers = (add_member(group.id, msisdn=f"071200000{n}", name=f"P{n}", actor="t") for n in (1, 2, 3))
        for a in approvers:
            grant(a.id, Capability.APPROVE_PAYOUT, actor="t")
        propose = lambda f: propose_withdrawal(m.id, f.id, amount="10", purpose="x", payee_name="x",
                                               payee_account="0799000000")
        p = propose(fund)
        with self.assertRaisesMessage(CommunityError, "open proposal or an unexecuted mandate"):
            close_fund(fund.id, actor="t")
        cancel_proposal(p.id, m.id)
        self.assertEqual(close_fund(fund.id, actor="t").status, "closed")
        close_fund(spare.id, actor="t")
        with self.assertRaisesMessage(GovernanceError, "is closed"):
            propose(spare)

    def test_a_fund_with_a_custodian_account_does_not_close_and_a_closed_fund_takes_none(self):
        from tests.scenario import Scenario
        s = Scenario()
        self.enterContext(s.acting())
        with self.assertRaisesMessage(CommunityError, "linked custodian account"):
            close_fund(s.fund.id, actor="t")
        closed = close_fund(open_fund(s.group.id, name="Closed", actor="t").id, actor="t")
        with self.assertRaisesMessage(CustodyError, "is closed"):
            link_external_account(closed.id, institution="Custodian Bank", account_number="0099", account_name="x",
                                  connector="bank_simulator", actor="t")
        with self.assertRaisesMessage(DatabaseError, "is closed"), transaction.atomic():
            ExternalAccount.objects.create(group_id=s.group.id, fund_id=closed.id, institution="Custodian Bank",
                                           account_number="0099", account_name="x", connector="bank_simulator")
