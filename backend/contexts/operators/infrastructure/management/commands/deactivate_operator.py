from django.core.management.base import BaseCommand, CommandError

from contexts.operators.infrastructure.models import Operator
from contexts.operators.public import (NotSignedIn, OperatorCapability, OperatorError, deactivate_operator,
                                       operator_at_console)


class Command(BaseCommand):
    help = "Deactivate a WEPL operator and end their sessions at once."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--by", required=True, help="your operator email")
        parser.add_argument("--code", required=True, help="your current authenticator code")

    def handle(self, *args, email, by, code, **options):
        target = Operator.objects.filter(email=email.strip().lower()).first()
        if target is None:
            raise CommandError("No such operator.")
        try:
            deactivate_operator(target.pk, by=operator_at_console(by, code, OperatorCapability.OPERATORS_MANAGE))
        except (NotSignedIn, OperatorError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(f"Deactivated operator {target.pk}.")
