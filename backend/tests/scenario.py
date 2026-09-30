"""Builds groups and payouts through public contracts only, for tests.

Each scenario is its own tenant (ADR-0009). Its helpers act inside that
tenant; a test touching its data directly does so inside ``s.acting()``."""
from contexts.communities.public import Role, add_member, create_group
from contexts.custody.public import link_external_account, sync as custody_sync
from contexts.governance.public import decide, eligible_approvers, propose_withdrawal, proposal_view
from contexts.ledger.public import fund_position, member_balances, trial_balance
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import provision_tenant, tenant
from simulators.im_bank import bank
from simulators.im_bank.connector import SimulatorConnector

RULES = {
    "approvals": [{"up_to": "20000", "approvers": "officials", "required": 2},
                  {"up_to": None, "approvers": "members", "required": 3}],
    "bank_charges": "pro_rata", "interest": "pro_rata",
}
PEOPLE = [
    ("0712000001", "Wanjiku Kamau", Role.CHAIR),
    ("0712000002", "Otieno Ouma", Role.TREASURER),
    ("0712000003", "Akinyi Njeri", Role.SECRETARY),
    ("0712000004", "Kiprono Cheruiyot", Role.MEMBER),
    ("0712000005", "Mutua Musyoka", Role.MEMBER),
]


class Scenario:
    def __init__(self, name="Umoja Savings Group", *, rules=None, people=PEOPLE, account="0012345678901",
                 opening_balance="0.00"):
        """A group is a tenant (ADR-0010): each scenario provisions its own."""
        from contexts.governance.public import adopt_constitution
        self.tenant_id = provision_tenant(name, actor="test").id
        with self.acting():
            self.group, self.fund = create_group(name, actor="test")
            adopt_constitution(self.group.id, rules or RULES, actor="test")
            self.m = [add_member(self.group.id, msisdn=n, name=nm, role=r, actor="test") for n, nm, r in people]
            self.account = account
            bank.open_account(account, name, opening_balance)
            self.ea = link_external_account(self.fund.id, institution="I&M Bank Kenya", account_number=account,
                                            account_name=name, connector="im_simulator", actor="test")

    def acting(self):
        """This scenario's tenant context."""
        return tenant(self.tenant_id)

    def sync(self, connector=None):
        with self.acting():
            return custody_sync(self.ea.id, connector or SimulatorConnector(sweep=True))

    def approve(self, amount, *, payee_account="0799000000", charged=None, proposer=None) -> str:
        """Propose and approve a withdrawal; returns the mandate reference."""
        with self.acting():
            return self._approve(amount, payee_account=payee_account, charged=charged, proposer=proposer)

    def _approve(self, amount, *, payee_account, charged, proposer) -> str:
        proposer = proposer or self.m[1]
        p = propose_withdrawal(proposer.id, self.fund.id, amount=amount, purpose="Test", payee_name="Supplier",
                               payee_account=payee_account, charged_member_id=charged.id if charged else None)
        for a in eligible_approvers(p.id):
            if proposal_view(p.id).mandate_reference:
                break
            decide(p.id, a.id, approve=True)
        return proposal_view(p.id).mandate_reference

    def balance_of(self, member) -> Money:
        with self.acting():
            return member_balances(self.fund.id).get(member.id, Money.zero())

    def position(self):
        with self.acting():
            return fund_position(self.fund.id)

    def assert_sound(self, tc):
        """The invariants I&M is asked to rely on."""
        with self.acting():
            return self._assert_sound(tc)

    def _assert_sound(self, tc):
        from contexts.custody.public import open_alerts, statement_lines
        tc.assertEqual(trial_balance(self.fund.id), 0)
        pos = self.position()
        tc.assertTrue(pos.invariant_holds, pos)
        alerted = {a["line_id"] for a in open_alerts(self.group.id, kind="unmatched_outflow")}
        for line in statement_lines(self.ea.id):
            tc.assertIsNotNone(line["outcome"], f"line {line['external_id']} was never accounted for")
            if line["kind"] == "withdrawal":
                tc.assertTrue(line["outcome"] in ("matched", "explained") or line["id"] in alerted, line)
        return pos


def act_for_new_tenant(testcase, name="Test tenant") -> int:
    """Provision a tenant and act for it until the test ends."""
    tenant_id = provision_tenant(name, actor="test").id
    testcase.enterContext(tenant(tenant_id))
    return tenant_id
