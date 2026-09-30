from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import import_string

from connectivity import services
from connectivity.models import ExternalAccount


class Command(BaseCommand):
    help = "Fetch statements for every connected account, ingest them, and reconcile."

    def handle(self, *args, **options):
        failures = 0
        for ea in ExternalAccount.objects.order_by("pk"):
            path = settings.WEPL_CONNECTORS.get(ea.connector)
            if path is None:
                run = services.reconcile(ea)  # statements arrive by upload for this account
                result = None
            else:
                result, run = services.sync(ea, import_string(path)(sweep=True))
            state = "balanced" if run.balanced else "NOT BALANCED"
            failures += not run.balanced
            self.stdout.write(f"{ea}: {state}; difference {run.difference}; "
                              f"new lines {result.new if result else 0}; open alerts {run.open_alerts}")
        if failures:
            self.stderr.write(f"{failures} account(s) did not reconcile.")
