from django.core.management.base import BaseCommand, CommandError

from contexts.operations.public import run_nightly


class Command(BaseCommand):
    help = ("The nightly run: sync and reconcile every account, check every fund's books, send queued messages, "
            "then email the operations digest. Exits non-zero if any job failed.")

    def handle(self, *args, **options):
        steps, digest = run_nightly()
        self.stdout.write(digest)
        failed = [s.name for s in steps if not s.ok]
        if failed:
            raise CommandError(f"Failed: {', '.join(failed)}.")
