from django.core.management.base import BaseCommand

from contexts.operations.public import operator_inbox


class Command(BaseCommand):
    help = "Every open problem in every group, urgent first, then oldest first."

    def add_arguments(self, parser):
        parser.add_argument("--operator", required=True, help="Who is looking; recorded in the audit trail.")

    def handle(self, *args, operator, **options):
        items = operator_inbox(actor=f"operator:{operator}")
        if not items:
            self.stdout.write("Nothing is open.")
        for i in items:
            when = f"{i.opened_at:%d %b %H:%M}" if i.opened_at else "never"
            self.stdout.write(f"{'URGENT ' if i.urgent else '       '}{i.group} | {i.kind.value} | {when} | {i.detail}")
