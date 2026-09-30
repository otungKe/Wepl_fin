"""Scenario builders shared by the tests and the demo command."""
from connectivity.models import ExternalAccount
from governance import services as gov
from governance.models import Membership
from simulator import bank

DEFAULT_RULES = {
    "approvals": [
        {"up_to": "20000", "approvers": "officials", "required": 2},
        {"up_to": None, "approvers": "members", "required": 3},
    ],
    "bank_charges": "pro_rata",
    "interest": "pro_rata",
}

PEOPLE = [
    ("0712000001", "Wanjiku Kamau", Membership.Role.CHAIR),
    ("0712000002", "Otieno Ouma", Membership.Role.TREASURER),
    ("0712000003", "Akinyi Njeri", Membership.Role.SECRETARY),
    ("0712000004", "Kiprono Cheruiyot", Membership.Role.MEMBER),
    ("0712000005", "Mutua Musyoka", Membership.Role.MEMBER),
]


def make_group(name="Umoja Savings Group", *, rules=None, people=PEOPLE, account_number="0012345678901",
               opening_balance="0.00"):
    group, fund = gov.create_group(name, actor="test")
    gov.adopt_constitution(group, rules or DEFAULT_RULES, actor="test")
    members = [gov.add_member(group, msisdn=m, name=n, role=r, actor="test") for m, n, r in people]
    bank.open_account(account_number, name, opening_balance)
    ea = ExternalAccount.objects.create(group=group, fund=fund, account_number=account_number,
                                        account_name=name, connector=ExternalAccount.Connector.IM_SIMULATOR)
    return group, fund, members, ea


def approve_withdrawal(members, fund, amount, *, payee_name="Supplier Ltd", payee_account="0799000000",
                       charged_member=None, proposer=None):
    """Propose and approve a withdrawal; returns the issued mandate."""
    proposer = proposer or members[1]
    proposal = gov.propose_withdrawal(proposer, fund, amount=amount, purpose="Test", payee_name=payee_name,
                                      payee_account=payee_account, charged_member=charged_member)
    for approver in gov.eligible_approvers(proposal):
        proposal.refresh_from_db()
        if proposal.status != proposal.Status.OPEN:
            break
        gov.decide(proposal, approver, approve=True)
    proposal.refresh_from_db()
    return proposal.mandate
