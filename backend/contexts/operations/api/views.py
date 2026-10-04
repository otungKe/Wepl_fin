"""The operator inbox over HTTP: a signed-in operator allowed
``operations.inbox``, with an authenticator code entered in the last few
minutes (ADR-0021). Reading every group is audited under their name."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from contexts.operators.public import COOKIE, NotSignedIn, OperatorCapability, authenticate

from ..application.inbox import operator_inbox


@require_GET
def inbox(request):
    try:
        op = authenticate(request.COOKIES.get(COOKIE, ""), OperatorCapability.INBOX)
    except NotSignedIn:
        return JsonResponse({"error": "Not signed in."}, status=401)
    items = operator_inbox(actor=op.actor)
    return JsonResponse({"items": [
        {"group_id": i.group_id, "group": i.group, "kind": i.kind.value, "urgent": i.urgent,
         "opened_at": i.opened_at.isoformat() if i.opened_at else None, "detail": i.detail} for i in items]})
