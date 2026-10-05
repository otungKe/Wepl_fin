"""Show where each member of a fund stands against its contribution rule."""
from django.core.management.base import BaseCommand, CommandError

from contexts.communities.public import CommunityError, fund_view
from contexts.contributions.public import ContributionsError, fund_standing
from contexts.tenancy.public import tenant


class Command(BaseCommand):
    help = "Arrears, paid-ahead amounts and late fines for one fund (ADR-0022). Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", dest="tenant_id", type=int, required=True)
        parser.add_argument("--fund", type=int, required=True)

    def handle(self, *args, tenant_id: int, fund: int, **options):
        with tenant(tenant_id):
            try:
                name = fund_view(fund).name
                rows = fund_standing(fund)
            except (CommunityError, ContributionsError) as exc:
                raise CommandError(str(exc)) from None
            if not rows:
                self.stdout.write(f"{name} has no contribution rule in the group's constitution.")
                return
            self.stdout.write(f"{name}, as of {rows[0].as_of}:")
            for r in rows:
                s = r.standing
                self.stdout.write(f"  {r.code:5} {r.name[:24]:24} due {s.due.amount:>10} paid {s.paid.amount:>10} "
                                  f"arrears {s.arrears.amount:>10} ahead {s.paid_ahead.amount:>9} "
                                  f"fines {s.fines_total.amount:>8}"
                                  + (f" written off {s.written_off.amount}" if s.written_off.is_positive else "")
                                  + ("" if r.active else " (left)"))

