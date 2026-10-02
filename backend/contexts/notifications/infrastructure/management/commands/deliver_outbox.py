from django.core.management.base import BaseCommand

from contexts.notifications.public import deliver_pending


class Command(BaseCommand):
    help = "Deliver queued notifications."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, limit, **options):
        self.stdout.write(f"Delivered {deliver_pending(limit)} message(s).")
