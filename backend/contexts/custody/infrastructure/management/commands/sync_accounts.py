from django.core.management.base import BaseCommand

from contexts.custody.public import all_accounts, connector_for, reconcile, sync


class Command(BaseCommand):
    help = "Fetch statements for every linked custodian account, account for them, and reconcile."

    def handle(self, *args, **options):
        failures = 0
        for ea in all_accounts():
            connector = connector_for(ea.connector, sweep=True)
            if connector is None:  # statements for this account arrive by upload
                result, run = None, reconcile(ea.id)
            else:
                result, run = sync(ea.id, connector)
            failures += not run.balanced
            self.stdout.write(f"{ea}: {'balanced' if run.balanced else 'NOT BALANCED'}; difference {run.difference}; "
                              f"new lines {result.new if result else 0}; open alerts {run.open_alerts}")
        if failures:
            self.stderr.write(f"{failures} account(s) did not reconcile.")
