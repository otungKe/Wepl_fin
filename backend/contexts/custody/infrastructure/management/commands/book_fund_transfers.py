from django.core.management.base import BaseCommand, CommandError

from contexts.custody.public import CustodyError, book_approved_transfers
from contexts.tenancy.public import tenant, tenant_ids


class Command(BaseCommand):
    help = ("Book every move between funds that a group has approved and custody has not booked yet (ADR-0024). "
            "A transfer whose money is no longer there fails, and the group is told. Run nightly.")

    def handle(self, *args, **options):
        booked = failed = 0
        errors = []
        for tenant_id in tenant_ids(reason="book approved fund transfers", actor="system"):
            with tenant(tenant_id):  # this group's transfers only, cleared on exit
                try:
                    b, f = book_approved_transfers()
                except CustodyError as exc:  # one group's problem does not stop the others
                    errors.append(str(exc))
                    continue
                booked, failed = booked + b, failed + f
        self.stdout.write(f"{booked} fund transfer(s) booked, {failed} failed.")
        if errors:
            raise CommandError("Could not book: " + " | ".join(errors))
