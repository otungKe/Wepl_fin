"""Operator sign-in over HTTP (ADR-0021). Every answer about a failed
attempt is the same, so the API never says which part was wrong or whether
an email exists. Requests must be JSON: with a SameSite=Strict cookie, that
keeps another site's form from acting as a signed-in operator."""
import json
from functools import wraps

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from ..application import sessions
from ..contract import COOKIE, NotSignedIn, OperatorError
from ..domain.signin import ABSOLUTE_LIMIT

REFUSED = {"error": "Not signed in."}


def _json_body(request) -> dict:
    if request.content_type != "application/json":
        raise OperatorError("Send JSON.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise OperatorError("Send JSON.") from None
    if not isinstance(data, dict):
        raise OperatorError("Send a JSON object.")
    return data


def _answer(view):
    @wraps(view)
    def wrapper(request):
        try:
            data = _json_body(request) if request.method == "POST" else {}
            return view(request, data, request.COOKIES.get(COOKIE, ""))
        except NotSignedIn:
            return JsonResponse(REFUSED, status=401)
        except OperatorError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    return wrapper


def set_cookie(response, token: str):
    response.set_cookie(COOKIE, token, max_age=int(ABSOLUTE_LIMIT.total_seconds()), path="/operators/",
                        secure=True, httponly=True, samesite="Strict")
    return response


@require_POST
@_answer
def sign_in(_request, data, _token):
    started = sessions.sign_in(str(data.get("email", "")), str(data.get("password", "")))
    if started is None:
        return JsonResponse({"error": "Email or password is wrong, or the account is locked."}, status=401)
    token, stage = started
    return set_cookie(JsonResponse({"next": stage}), token)


@require_POST
@_answer
def change_password(_request, data, token):
    return JsonResponse({"next": sessions.change_password(token, str(data.get("new_password", "")))})


@require_POST
@_answer
def begin_enrolment(_request, _data, token):
    return JsonResponse({"otpauth_uri": sessions.begin_enrolment(token)})


def _code_step(action):
    @require_POST
    @_answer
    def view(_request, data, token):
        if not action(token, str(data.get("code", ""))):
            return JsonResponse({"error": "That code is wrong or was already used."}, status=401)
        return JsonResponse({"next": "full"})
    return view


confirm_enrolment = _code_step(sessions.confirm_enrolment)
enter_code = _code_step(sessions.enter_code)
step_up = _code_step(sessions.step_up)


@require_POST
@_answer
def sign_out(_request, _data, token):
    sessions.sign_out(token)
    response = JsonResponse({"signed_out": True})
    response.delete_cookie(COOKIE, path="/operators/", samesite="Strict")
    return response


@require_GET
@_answer
def me(_request, _data, token):
    op = sessions.authenticate(token)
    return JsonResponse({"id": op.id, "email": op.email, "name": op.name, "role": op.role})
