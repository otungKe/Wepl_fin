from django.core.management.base import BaseCommand, CommandError

from contexts.custody.public import CustodyError, all_accounts, connector_for, reconcile, sync
from contexts.tenancy.public import tenant, tenant_ids


class Command(BaseCommand):
    help = ("Fetch statements for every linked custodian account, closed ones included, account for them, and "
            "reconcile. Fails if any account could not be synced, e.g. a closed account the custodian reports "
            "new activity on.")

    def handle(self, *args, **options):
        failures, errors = 0, []
        for tenant_id in tenant_ids(reason="sync and reconcile every custodian account", actor="system"):
            with tenant(tenant_id):  # set for this tenant's accounts only, cleared on exit
                for ea in all_accounts():
                    try:
                        failures += not self._sync(ea)
                    except CustodyError as exc:  # one account's problem does not stop the others
                        errors.append(f"{ea}: {exc}")
        if failures:
            self.stderr.write(f"{failures} account(s) did not reconcile.")
        if errors:
            raise CommandError("Could not sync: " + " | ".join(errors))

    def _sync(self, ea) -> bool:
        connector = connector_for(ea.connector, sweep=True)
        if connector is None:  # statements for this account arrive by upload
            result, run = None, reconcile(ea.id)
        else:
            result, run = sync(ea.id, connector)
        self.stdout.write(f"{ea}: {'balanced' if run.balanced else 'NOT BALANCED'}; difference {run.difference}; "
                          f"new lines {result.new if result else 0}; open alerts {run.open_alerts}")
        return run.balanced
