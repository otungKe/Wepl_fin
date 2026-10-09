from django.core.management.base import BaseCommand, CommandError

from contexts.ledger.public import check_books
from contexts.tenancy.public import tenant, tenant_ids


class Command(BaseCommand):
    help = ("Check every fund's books in every tenant: trial balance zero, the fund position invariant, every entry "
            "balanced on its own, transfers paired, and the balance queries agreeing. Records each result and alerts "
            "on failure. Run nightly; exits non-zero on any failure.")

    def handle(self, *args, **options):
        checked = failed = unchecked = 0
        for tenant_id in tenant_ids(reason="nightly ledger integrity check", actor="system"):
            try:
                with tenant(tenant_id):  # each tenant's books, and its results, in its own transaction
                    results = check_books()
            except Exception as exc:  # one tenant's error must not leave the others unchecked
                unchecked += 1
                self.stderr.write(f"COULD NOT CHECK tenant {tenant_id}: {type(exc).__name__}: {exc}")
                continue
            for c in results:
                checked += 1
                if not c.passed:
                    failed += 1
                    self.stderr.write(
                        f"FAILED fund {c.fund_id} {c.currency}: trial balance {c.trial_balance}, invariant holds "
                        f"{c.invariant_holds}, broken entries {c.broken_entries}, unpaired transfers "
                        f"{c.unpaired_transfers}, queries agree {c.queries_agree} (check {c.pk})")
        self.stdout.write(f"{checked} fund book(s) checked, {failed} failed, {unchecked} tenant(s) not checked.")
        if failed or unchecked:
            raise CommandError(f"{failed} fund book(s) failed the integrity check; {unchecked} tenant(s) could not "
                               "be checked.")
