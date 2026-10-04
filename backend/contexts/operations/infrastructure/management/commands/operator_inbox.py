from django.core.management.base import BaseCommand, CommandError

from contexts.operations.public import operator_inbox
from contexts.operators.public import NotSignedIn, OperatorCapability, operator_at_console


class Command(BaseCommand):
    help = ("Every open problem in every group, urgent first, then oldest first. Names a real operator "
            "(ADR-0021): their email and a current authenticator code; the look is audited under their name.")

    def add_arguments(self, parser):
        parser.add_argument("--operator", required=True, help="your operator email")
        parser.add_argument("--code", required=True, help="your current authenticator code")

    def handle(self, *args, operator, code, **options):
        try:
            op = operator_at_console(operator, code, OperatorCapability.INBOX)
        except NotSignedIn as exc:
            raise CommandError(str(exc)) from None
        items = operator_inbox(actor=op.actor)
        if not items:
            self.stdout.write("Nothing is open.")
        for i in items:
            when = f"{i.opened_at:%d %b %H:%M}" if i.opened_at else "never"
            self.stdout.write(f"{'URGENT ' if i.urgent else '       '}{i.group} | {i.kind.value} | {when} | {i.detail}")
