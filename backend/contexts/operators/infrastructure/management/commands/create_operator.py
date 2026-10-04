from django.core.management.base import BaseCommand, CommandError

from contexts.operators.public import (NotSignedIn, OperatorCapability, OperatorError, create_operator,
                                       operator_at_console)


class Command(BaseCommand):
    help = ("Create a WEPL operator and print a one-time password to hand over in person. The first operator "
            "(an admin) needs no --by; after that an admin names themselves with --by and --code.")

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("name")
        parser.add_argument("role", help="support, onboarding or admin")
        parser.add_argument("--by", help="your operator email")
        parser.add_argument("--code", help="your current authenticator code")

    def handle(self, *args, email, name, role, by=None, code=None, **options):
        try:
            admin = operator_at_console(by, code, OperatorCapability.OPERATORS_MANAGE) if by else None
            op, one_time = create_operator(email, name, role, by=admin)
        except (NotSignedIn, OperatorError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"Created operator {op.id} ({op.role}). One-time password: {one_time}")
        self.stdout.write("They must change it and enrol an authenticator at first sign-in.")
