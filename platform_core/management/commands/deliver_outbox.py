from django.core.management.base import BaseCommand

from platform_core.outbox import deliver_pending


class Command(BaseCommand):
    help = "Deliver pending outbox events (run from a scheduled job)."

    def handle(self, *args, **options):
        self.stdout.write(f"Delivered {deliver_pending()} event(s).")
