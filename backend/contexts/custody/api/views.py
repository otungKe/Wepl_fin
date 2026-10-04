"""WEPL's first public endpoints (ADR-0019): the bank asks whether a
payment reference is good for a group's account, and tells WEPL about each
payment into it. Both are off unless a shared secret is configured, and both
refuse anything unsigned."""
import json
import time

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST

from ..application.collections import UnknownAccount, check_reference, receive
from .payload import BadPayload, account_number, bank_line
from .signature import refusal


def _verified(request) -> dict:
    secret = settings.WEPL_COLLECTIONS_SECRET
    if not secret:
        raise Http404()
    why = refusal(secret, timestamp=request.headers.get("X-WEPL-Timestamp", ""),
                  signature=request.headers.get("X-WEPL-Signature", ""), body=request.body, now=time.time())
    if why:
        raise PermissionError(why)
    try:
        data = json.loads(request.body)
    except ValueError:
        raise BadPayload("Not JSON.") from None
    if not isinstance(data, dict):
        raise BadPayload("Expected a JSON object.")
    return data


def _guarded(view):
    def wrapper(request):
        try:
            return view(request, _verified(request))
        except PermissionError as exc:
            return JsonResponse({"error": str(exc)}, status=401)
        except BadPayload as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    return require_POST(wrapper)


@_guarded
def validate(_request, data):
    check = check_reference(account_number(data), str(data.get("reference", "")))
    return JsonResponse({"accepted": check.accepted, "name": check.group_name, "reason": check.reason})


@_guarded
def notify(_request, data):
    """200 only once the payment is recorded; any failure is a 5xx, so the
    bank retries. A retry of a recorded payment changes nothing. A payment
    for an account WEPL does not know is refused (404), never parked."""
    try:
        result = receive(account_number(data), [bank_line(data)])
    except UnknownAccount:
        return JsonResponse({"error": "No WEPL group collects into that account."}, status=404)
    return JsonResponse({"status": "received", "duplicate": bool(result.duplicates),
                         "conflict": bool(result.conflicts)})
