"""The 20-minute I&M demo from the custody design, as one repeatable script.

It runs against the configured database, creating a fresh group each time.
"""
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from connectivity import reports
from connectivity import services as conn
from connectivity.models import Alert, ExternalAccount, StatementLine
from governance import services as gov
from governance.models import Membership
from ledger.models import JournalLine
from platform_core.models import OutboxEvent
from simulator import bank
from simulator.bank import Faults, SimulatorConnector

R = Membership.Role
PEOPLE = [
    ("0712000001", "Wanjiku Kamau", R.CHAIR, "8000"),
    ("0712000002", "Otieno Ouma", R.TREASURER, "8000"),
    ("0712000003", "Akinyi Njeri", R.SECRETARY, "7000"),
    ("0712000004", "Kiprono Cheruiyot", R.MEMBER, "7000"),
    ("0712000005", "Mutua Musyoka", R.MEMBER, "6000"),
    ("0712000006", "Halima Abdi", R.MEMBER, "6000"),
]
RULES = {
    "approvals": [{"up_to": "20000", "approvers": "officials", "required": 2},
                  {"up_to": None, "approvers": "members", "required": 4}],
    "bank_charges": "pro_rata", "interest": "pro_rata", "mandate_valid_days": 14,
}


class Command(BaseCommand):
    help = "Run the scripted I&M custody demo with a simulated Chama Account and a faulty feed."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42)

    def step(self, title):
        self.stdout.write("\n" + self.style.MIGRATE_HEADING(title))

    def say(self, text=""):
        self.stdout.write("  " + text)

    def recon(self, run):
        state = self.style.SUCCESS("BALANCED") if run.balanced else self.style.ERROR("NOT BALANCED")
        self.say(f"Reconciliation #{run.pk}: {state}")
        self.say(f"  bank balance {run.statement_balance}  |  WEPL cash {run.ledger_cash}  |  "
                 f"difference {run.difference}")
        self.say(f"  members {run.member_interests} + unattributed {run.unattributed} + retained "
                 f"{run.retained} - unexplained {run.unexplained_out}")
        if run.sequence_gaps:
            self.say(f"  missing bank sequence numbers: {run.sequence_gaps}")

    def handle(self, *args, seed, **options):
        number = "01" + timezone.now().strftime("%y%m%d%H%M%S")
        name = f"Umoja Savings Group {number[-6:]}"

        self.step("1. Onboarding: group, constitution, members, existing I&M Chama Account")
        group, fund = gov.create_group(name, actor="operator")
        c = gov.adopt_constitution(group, RULES, actor="operator")
        members = {n: gov.add_member(group, msisdn=m, name=n, role=r, actor="operator")
                   for m, n, r, _ in PEOPLE}
        opening = sum(Decimal(b) for *_, b in PEOPLE) + Decimal("3000")
        bank.open_account(number, name, opening)
        ea = ExternalAccount.objects.create(group=group, fund=fund, account_number=number, account_name=name,
                                            connector=ExternalAccount.Connector.IM_SIMULATOR)
        conn.record_opening_balances(ea, statement_balance=opening, actor="treasurer",
                                     member_balances={members[n]: b for _, n, _, b in PEOPLE})
        self.say(f"{name}: {len(members)} members, constitution v{c.version}, I&M account {number}")
        self.say(f"Opening balance KES {opening}: KES {opening - 3000} signed off per member, "
                 f"KES 3000 nobody can account for is held as unattributed")

        self.step("2. Contributions through paybill 542542 (one payer is not a member)")
        for msisdn, n, _, _ in PEOPLE:
            bank.deposit(number, "5000", msisdn="254" + msisdn[1:], name=n.upper())
        bank.deposit(number, "5000", msisdn="254733444555", name="JOHN OUMA")

        self.step("3. A faulty push feed: duplicates, reordering, and a missing line")
        feed = SimulatorConnector(Faults(duplicate_rate=0.5, withhold_rate=0.2, reorder=True, seed=seed))
        result, run = conn.sync(ea, feed)
        self.say(f"Received {result.new} new lines, ignored {result.duplicates} duplicates")
        self.recon(run)

        self.step("4. End-of-day statement sweep heals the gap")
        result, run = conn.sync(ea, SimulatorConnector(sweep=True))
        self.say(f"Received {result.new} missing line(s), ignored {result.duplicates} already seen")
        self.recon(run)

        self.step("5. Treasurer identifies the unknown payer, once")
        unknown = StatementLine.objects.get(external_account=ea, counterparty_msisdn="254733444555")
        conn.attribute_payment(unknown, members["Otieno Ouma"], actor="treasurer")
        self.say("JOHN OUMA (0733 444 555) pays for Otieno Ouma; remembered for next time")

        self.step("6. Approved withdrawal: proposal, two officials approve, mandate, payment")
        proposal = gov.propose_withdrawal(members["Otieno Ouma"], fund, amount="15000",
                                          purpose="Land search and survey fees", payee_name="Ardhi Surveyors",
                                          payee_account="0799111222")
        gov.decide(proposal, members["Wanjiku Kamau"], approve=True, source="app")
        gov.decide(proposal, members["Akinyi Njeri"], approve=True, source="app")
        proposal.refresh_from_db()
        mandate = proposal.mandate
        self.say(f"Mandate {mandate.reference} issued for KES {mandate.amount}")
        bank.withdraw(number, "15000", narration=f"PESALINK ARDHI SURVEYORS {mandate.reference}",
                      payee_name="ARDHI SURVEYORS")

        self.step("7. Money leaves without approval")
        bank.withdraw(number, "8000", narration="CASH WITHDRAWAL BRANCH", payee_name="CASH")
        bank.credit_interest(number, "120")
        bank.charge(number, "30", "PESALINK CHARGE")
        result, run = conn.sync(ea, SimulatorConnector(sweep=True))
        mandate.refresh_from_db()
        self.say(f"Mandate {mandate.reference}: {mandate.status}")
        for alert in Alert.objects.filter(group=group, kind=Alert.Kind.UNMATCHED_OUTFLOW):
            self.say(self.style.WARNING(f"ALERT to all {len(members)} members: {alert.message}"))
        self.recon(run)

        self.step("8. Tampering is refused by the database itself")
        try:
            with transaction.atomic():
                JournalLine.objects.filter(entry__group_id=group.pk).update(amount=1)
        except DatabaseError as exc:
            self.say(f"UPDATE journal line -> {str(exc).splitlines()[0]}")
        try:
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("DELETE FROM connectivity_statementline WHERE external_account_id = %s", [ea.pk])
        except DatabaseError as exc:
            self.say(f"DELETE statement line -> {str(exc).splitlines()[0]}")

        self.step("9. Member statements")
        for membership in members.values():
            s = reports.member_statement(membership, fund.pk)
            self.say(f"{s['code']} {s['member']:<20} KES {s['balance']:>10}")
        summary = reports.group_summary(ea)
        self.say(f"Group cash KES {summary['cash']} = members {summary['member_interests']} + unattributed "
                 f"{summary['unattributed']} + retained {summary['retained']} - unexplained "
                 f"{summary['unexplained_out']}")

        self.step("10. Notifications queued (delivered by the outbox worker; SMS provider on hold)")
        topics = Counter(OutboxEvent.objects.filter(created_at__gte=group.created_at).values_list("topic", flat=True))
        for topic, count in sorted(topics.items()):
            self.say(f"{topic:<32} {count}")
