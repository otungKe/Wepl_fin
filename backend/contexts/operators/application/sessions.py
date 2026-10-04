"""Staged sign-in and operator sessions (ADR-0021).

Wrong answers are recorded and returned as False rather than raised, so the
failure count survives the request's transaction."""
import hashlib
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from ..contract import NotSignedIn, OperatorError, OperatorView, Stage
from ..domain import signin, totp
from ..domain.capabilities import STEP_UP, allowed
from ..infrastructure.models import Operator, OperatorSession
from ..infrastructure.secrets import seal, unseal
from .log import log

_DUMMY = make_password("not-a-password-anyone-has")


def view(o: Operator) -> OperatorView:
    return OperatorView(id=o.pk, email=o.email, name=o.name, role=o.role, active=o.active)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session(token: str) -> OperatorSession:
    s = (OperatorSession.objects.select_for_update().select_related("operator")
         .filter(token_hash=_hash(token or "")).first())
    if s is None:
        raise NotSignedIn("signed out")
    return s


def _live(s: OperatorSession, now) -> None:
    """Expired, ended or deactivated sessions answer nothing, at any stage."""
    if s.ended_at or not s.operator.active or now - s.created_at > signin.ABSOLUTE_LIMIT \
            or now - s.last_seen_at > signin.IDLE_LIMIT:
        raise NotSignedIn("signed out")


def _at(token: str, stage: Stage) -> OperatorSession:
    now = timezone.now()
    s = _session(token)
    _live(s, now)
    if s.stage != stage:
        raise NotSignedIn("not at this step of sign-in")
    s.last_seen_at = now
    return s


def _failed(o: Operator, what: str) -> None:
    now = timezone.now()
    o.failed_attempts, o.locked_until = signin.after_failure(o.failed_attempts, now=now)
    o.save(update_fields=["failed_attempts", "locked_until"])
    log(f"operator.{what}_failed", operator=o, actor=f"operator:{o.pk}")
    if o.locked_until:
        OperatorSession.objects.filter(operator=o, ended_at__isnull=True).update(ended_at=now)
        log("operator.locked", operator=o, actor="system", until=o.locked_until.isoformat())


def _locked(o: Operator) -> bool:
    return o.locked_until is not None and o.locked_until > timezone.now()


def sign_in(email: str, password: str) -> tuple[str, Stage] | None:
    """A new session at its first step, or None. None is the only answer for
    a wrong password, an unknown email, a locked or deactivated operator."""
    o = Operator.objects.select_for_update().filter(email=(email or "").strip().lower()).first()
    if o is None:
        check_password(password or "", _DUMMY)  # the same work as a real check
        log("operator.sign_in_unknown", operator=None, actor="anonymous")
        return None
    if not o.active or _locked(o):
        check_password(password or "", _DUMMY)
        log("operator.sign_in_refused", operator=o, actor="anonymous", locked=_locked(o), active=o.active)
        return None
    if not check_password(password or "", o.password):
        _failed(o, "password")
        return None
    o.failed_attempts = 0
    o.save(update_fields=["failed_attempts"])
    stage = signin.stage_after_password(must_change_password=o.must_change_password, enrolled=bool(o.enrolled_at))
    token, now = secrets.token_urlsafe(32), timezone.now()
    OperatorSession.objects.create(operator=o, token_hash=_hash(token), stage=stage, created_at=now, last_seen_at=now)
    log("operator.password_accepted", operator=o, actor=f"operator:{o.pk}", stage=stage)
    return token, stage


def change_password(token: str, new_password: str) -> Stage:
    s = _at(token, Stage.CHANGE_PASSWORD)
    o = s.operator
    if why := signin.password_refusal(new_password, email=o.email):
        raise OperatorError(f"Choose another password: {why}.")
    if check_password(new_password, o.password):
        raise OperatorError("Choose another password: it must differ from the one you were given.")
    o.password, o.must_change_password = make_password(new_password), False
    o.save(update_fields=["password", "must_change_password"])
    s.stage = signin.stage_after_password(must_change_password=False, enrolled=bool(o.enrolled_at))
    s.save(update_fields=["stage", "last_seen_at"])
    log("operator.password_changed", operator=o, actor=f"operator:{o.pk}")
    return s.stage


def begin_enrolment(token: str) -> str:
    """A new authenticator secret, as the link an authenticator app scans."""
    s = _at(token, Stage.ENROL)
    secret = totp.new_secret()
    s.pending_authenticator = seal(secret)
    s.save(update_fields=["pending_authenticator", "last_seen_at"])
    return totp.provisioning_uri(secret, account=s.operator.email)


def confirm_enrolment(token: str, code: str) -> bool:
    s = _at(token, Stage.ENROL)
    o = s.operator
    if s.pending_authenticator is None:
        raise OperatorError("Start enrolment first.")
    secret = unseal(s.pending_authenticator)
    step = totp.matching_step(secret, code, now=timezone.now().timestamp(), last_used=None)
    if step is None:
        _failed(o, "enrolment_code")
        return False
    o.authenticator, o.enrolled_at, o.last_code_step, o.failed_attempts = seal(secret), timezone.now(), step, 0
    o.save(update_fields=["authenticator", "enrolled_at", "last_code_step", "failed_attempts"])
    s.pending_authenticator, s.stage, s.step_up_at = None, Stage.FULL, timezone.now()
    s.save(update_fields=["pending_authenticator", "stage", "step_up_at", "last_seen_at"])
    log("operator.enrolled", operator=o, actor=f"operator:{o.pk}")
    return True


def _code_ok(o: Operator, code: str) -> bool:
    step = totp.matching_step(unseal(o.authenticator), code, now=timezone.now().timestamp(),
                              last_used=o.last_code_step)
    if step is None:
        _failed(o, "code")
        return False
    o.last_code_step, o.failed_attempts = step, 0
    o.save(update_fields=["last_code_step", "failed_attempts"])
    return True


def enter_code(token: str, code: str) -> bool:
    s = _at(token, Stage.CODE)
    if not _code_ok(s.operator, code):
        return False
    s.stage, s.step_up_at = Stage.FULL, timezone.now()
    s.save(update_fields=["stage", "step_up_at", "last_seen_at"])
    log("operator.signed_in", operator=s.operator, actor=f"operator:{s.operator.pk}")
    return True


def step_up(token: str, code: str) -> bool:
    s = _at(token, Stage.FULL)
    if not _code_ok(s.operator, code):
        return False
    s.step_up_at = timezone.now()
    s.save(update_fields=["step_up_at", "last_seen_at"])
    log("operator.stepped_up", operator=s.operator, actor=f"operator:{s.operator.pk}")
    return True


def sign_out(token: str) -> None:
    s = OperatorSession.objects.filter(token_hash=_hash(token or ""), ended_at__isnull=True).first()
    if s:
        s.ended_at = timezone.now()
        s.save(update_fields=["ended_at"])
        log("operator.signed_out", operator=s.operator, actor=f"operator:{s.operator_id}")


def authenticate(token: str, capability: str | None = None) -> OperatorView:
    """The operator behind a finished, live session, allowed ``capability``.
    Raises NotSignedIn otherwise; nothing about the reason leaks beyond it."""
    now = timezone.now()
    s = _session(token)
    o = s.operator
    facts = signin.SessionFacts(stage=Stage(s.stage), created_at=s.created_at, last_seen_at=s.last_seen_at,
                                step_up_at=s.step_up_at, ended=s.ended_at is not None, operator_active=o.active)
    if why := signin.session_refusal(facts, now=now, step_up=capability in STEP_UP):
        raise NotSignedIn(why)
    if capability is not None and not allowed(o.role, capability):
        raise NotSignedIn("not allowed")
    s.last_seen_at = now
    s.save(update_fields=["last_seen_at"])
    return view(o)
