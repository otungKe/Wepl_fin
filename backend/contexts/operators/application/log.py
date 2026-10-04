from ..infrastructure.models import Operator, OperatorEvent


def log(action: str, *, operator: Operator | None, actor: str, **data) -> None:
    OperatorEvent.objects.create(operator=operator, action=action, actor=actor, data=data)
