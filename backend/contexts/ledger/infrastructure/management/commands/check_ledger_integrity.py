from django.core.management.base import BaseCommand, CommandError

from contexts.ledger.public import check_books
from contexts.tenancy.public import tenant, tenant_ids


class Command(BaseCommand):
    help = ("Check every fund's books in every tenant: trial balance zero and the fund position invariant. "
            "Records each result and alerts on failure. Run nightly; exits non-zero on any failure.")

    def handle(self, *args, **options):
        checked = failed = 0
        for tenant_id in tenant_ids(reason="nightly ledger integrity check", actor="system"):
            with tenant(tenant_id):  # each tenant's books, and its results, in its own transaction
                for c in check_books():
                    checked += 1
                    if not c.passed:
                        failed += 1
                        self.stderr.write(f"FAILED fund {c.fund_id} {c.currency}: trial balance {c.trial_balance}, "
                                          f"invariant holds {c.invariant_holds} (check {c.pk})")
        self.stdout.write(f"{checked} fund book(s) checked, {failed} failed.")
        if failed:
            raise CommandError(f"{failed} fund book(s) failed the integrity check.")
