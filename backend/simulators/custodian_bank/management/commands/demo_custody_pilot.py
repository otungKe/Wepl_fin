"""The 20-minute custody demo from the custody design, as one repeatable script.
It drives the system only through each context's public surface, exactly as
the product will. Runs against the configured database, with a fresh group."""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from contexts.communities.public import add_member, create_group, open_fund
from contexts.custody import public as custody
from contexts.governance.public import Capability, adopt_constitution, decide, grant, propose_withdrawal, proposal_view
from contexts.notifications.public import topics_since
from contexts.shared_kernel.money import Money
from contexts.tenancy.public import tenant
from simulators.custodian_bank import bank
from simulators.custodian_bank.connector import Faults, SimulatorConnector

PEOPLE = [
    ("0712000001", "Wanjiku Kamau", "Chair", "8000"),
    ("0712000002", "Otieno Ouma", "Treasurer", "8000"),
    ("0712000003", "Akinyi Njeri", "Secretary", "7000"),
    ("0712000004", "Kiprono Cheruiyot", "", "7000"),
    ("0712000005", "Mutua Musyoka", "", "6000"),
    ("0712000006", "Halima Abdi", "", "6000"),
]
SIGNATORY = (Capability.APPROVE_PAYOUT, Capability.CANCEL_PAYOUT, Capability.CORRECT_RECORDS)
RULES = {"approvals": [{"up_to": "20000", "approvers": "designated", "required": 2},
                       {"up_to": None, "approvers": "members", "required": 4}],
         "bank_charges": "pro_rata", "interest": "pro_rata", "mandate_valid_days": 14}


class Command(BaseCommand):
    help = "Run the scripted custody demo with a simulated Chama Account and a faulty feed."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42)

    def step(self, title):
        self.stdout.write("\n" + self.style.MIGRATE_HEADING(title))

    def say(self, text=""):
        self.stdout.write("  " + text)

    def recon(self, run):
        state = self.style.SUCCESS("BALANCED") if run.balanced else self.style.ERROR("NOT BALANCED")
        self.say(f"Reconciliation #{run.id}: {state}")
        self.say(f"  bank balance {run.statement_balance}  |  WEPL cash {run.ledger_cash}  |  difference {run.difference}")
        self.say(f"  members {run.member_interests} + unattributed {run.unattributed} + retained {run.retained} "
                 f"- unexplained {run.unexplained_out}")
        if run.sequence_gaps:
            self.say(f"  missing bank sequence numbers: {run.sequence_gaps}")
        if run.balance_breaks:
            self.say(f"  running balance broken at sequence numbers: {run.balance_breaks}")

    def handle(self, *args, seed, **options):
        started = timezone.now()
        number = "01" + started.strftime("%y%m%d%H%M%S")
        name = f"Umoja Savings Group {number[-6:]}"
        group = create_group(name, actor="operator")  # founding the group establishes its tenant (ADR-0013)
        with tenant(group.tenant_id):
            self.pilot(group, name, number, started, seed)
        self.isolation(group.tenant_id, number)

    def pilot(self, group, name, number, started, seed):
        self.step("1. Onboarding: group (its own tenant), fund, constitution, members, existing Chama Account at the custodian bank")
        fund = open_fund(group.id, name="Main savings", actor="operator")
        version = adopt_constitution(group.id, RULES, actor="operator")
        members = {n: add_member(group.id, msisdn=m, name=n, title=t, actor="operator") for m, n, t, _ in PEOPLE}
        for m, n, t, _ in PEOPLE:  # the constitution's officials get its powers; a title alone grants nothing
            if t:
                for c in SIGNATORY:
                    grant(members[n].id, c, actor="operator")
        opening = Money("3000")
        for *_, b in PEOPLE:
            opening += Money(b)
        bank.open_account(number, name, opening.amount)
        ea = custody.link_external_account(fund.id, institution="Custodian Bank", account_number=number,
                                           account_name=name, connector="bank_simulator", actor="operator")
        custody.record_opening_balances(ea.id, statement_balance=opening.amount, by=members["Otieno Ouma"].id,
                                        confirmed_by=members["Wanjiku Kamau"].id,
                                        member_balances={members[n].id: b for _, n, _, b in PEOPLE})
        self.say(f"{name}: {len(members)} members, constitution v{version}, {ea}")
        self.say(f"Opening balance {opening}: members' balances signed off by the treasurer and the chair; "
                 f"KES 3,000 nobody can account for is held as unattributed")

        self.step("2. Contributions through paybill 542542 (one payer is not a member)")
        for msisdn, n, _, _ in PEOPLE:
            bank.deposit(number, "5000", msisdn="254" + msisdn[1:], name=n.upper())
        bank.deposit(number, "5000", msisdn="254733444555", name="JOHN OUMA")

        self.step("3. A faulty push feed: duplicates, reordering, and a missing line")
        feed = SimulatorConnector(Faults(duplicate_rate=0.5, withhold_rate=0.2, reorder=True, seed=seed))
        result, run = custody.sync(ea.id, feed)
        self.say(f"Received {result.new} new lines, ignored {result.duplicates} duplicates")
        self.recon(run)

        self.step("4. End-of-day statement sweep heals the gap")
        result, run = custody.sync(ea.id, SimulatorConnector(sweep=True))
        self.say(f"Received {result.new} missing line(s), ignored {result.duplicates} already seen")
        self.recon(run)

        self.step("5. A member granted correct_records identifies the unknown payer, once")
        line_id = self._line_from(ea.id, "254733444555")
        try:
            custody.attribute_payment(line_id, members["Otieno Ouma"].id, by=members["Otieno Ouma"].id)
        except custody.CustodyError as exc:
            self.say(f"Treasurer crediting their own account: refused ({exc})")
        custody.attribute_payment(line_id, members["Otieno Ouma"].id, by=members["Akinyi Njeri"].id)
        self.say("JOHN OUMA (0733 444 555) pays for Otieno Ouma; remembered for next time")

        self.step("6. Approved withdrawal: proposal, two designated approvers approve, mandate, payment")
        p = propose_withdrawal(members["Otieno Ouma"].id, fund.id, amount="15000", purpose="Land search and survey fees",
                               payee_name="Ardhi Surveyors", payee_account="0799111222")
        decide(p.id, members["Wanjiku Kamau"].id, approve=True)
        decide(p.id, members["Akinyi Njeri"].id, approve=True)
        reference = proposal_view(p.id).mandate_reference
        self.say(f"Mandate {reference} issued for KES 15,000.00")
        bank.withdraw(number, "15000", narration=f"PESALINK ARDHI SURVEYORS {reference}", payee_name="ARDHI SURVEYORS")

        self.step("7. Money leaves without approval")
        bank.withdraw(number, "8000", narration="CASH WITHDRAWAL BRANCH", payee_name="CASH")
        bank.credit_interest(number, "120")
        bank.charge(number, "30", "PESALINK CHARGE")
        result, run = custody.sync(ea.id, SimulatorConnector(sweep=True))
        for alert in custody.open_alerts(group.id, kind="unmatched_outflow"):
            self.say(self.style.WARNING(f"ALERT to all {len(members)} members: {alert['message']}"))
        self.recon(run)

        self.step("8. Tampering is refused by the database itself")
        for label, sql in (("UPDATE journal line", "UPDATE ledger_journalline SET amount = 1"),
                           ("DELETE statement line", "DELETE FROM custody_statementline")):
            try:
                with transaction.atomic(), connection.cursor() as cur:
                    cur.execute(sql)
            except DatabaseError as exc:
                self.say(f"{label} -> {str(exc).splitlines()[0]}")

        self.step("9. Member statements")
        for m in members.values():
            s = custody.member_statement(m.id, fund.id)
            self.say(f"{s['code']} {s['member']:<20} KES {s['balance']:>10}")
        pos = custody.group_summary(ea.id)["position"]
        self.say(f"Cash {pos.cash} = members {pos.member_interests} + unattributed {pos.unattributed} + retained "
                 f"{pos.retained} - unexplained {pos.unexplained_out}")

        self.step("10. One shilling, end to end: the trail for the survey payment")
        trail = custody.line_trail(self._line_from(ea.id, reference=reference))
        self.say(f"{trail['kind']} {trail['amount']} bank txn {trail['external_id']}")
        for r in trail["resolutions"]:
            self.say(f"  -> {r['outcome']}: mandate {r['mandate_id']}, journal entry {r['journal_entry_id']}, "
                     f"by {r['actor']} ({r['note']})")

        self.step("11. Notifications queued (delivered by the outbox worker; SMS provider on hold)")
        for topic, count in sorted(Counter(topics_since(started)).items()):
            self.say(f"{topic:<32} {count}")

    def isolation(self, tenant_id, number):
        self.step("12. Another group (another tenant) sees nothing of this group, even with raw SQL")
        neighbour = create_group("Neighbouring group", actor="operator").tenant_id
        with tenant(neighbour), connection.cursor() as cur:
            for table in ("ledger_journalentry", "custody_statementline", "communities_membership"):
                cur.execute(f"SELECT count(*) FROM {table}")
                self.say(f"{table:<26} rows visible to the neighbour: {cur.fetchone()[0]}")
        with tenant(tenant_id), connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM ledger_journalentry")
            self.say(f"{'ledger_journalentry':<26} rows visible to this group's tenant: {cur.fetchone()[0]}")

    def _line_from(self, ea_id, msisdn=None, reference=None):
        """Find a statement line the way the treasurer would: by what the bank showed."""
        for line in custody.statement_lines(ea_id):
            if (msisdn and line["counterparty_msisdn"] == msisdn) or (reference and reference in line["narration"]):
                return line["id"]
        raise LookupError("No such statement line.")
