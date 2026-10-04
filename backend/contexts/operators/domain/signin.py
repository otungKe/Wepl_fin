"""The rules of an operator session (ADR-0021). Pure: times are passed in."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

IDLE_LIMIT = timedelta(minutes=30)
ABSOLUTE_LIMIT = timedelta(hours=12)
STEP_UP_WINDOW = timedelta(minutes=10)
MAX_FAILURES = 5
LOCK_FOR = timedelta(minutes=15)
MIN_PASSWORD = 12


class Stage(StrEnum):
    """How far sign-in has got. Only FULL reaches anything but the next step."""
    CHANGE_PASSWORD = "change_password"
    ENROL = "enrol"
    CODE = "code"
    FULL = "full"


def stage_after_password(*, must_change_password: bool, enrolled: bool) -> Stage:
    if must_change_password:
        return Stage.CHANGE_PASSWORD
    return Stage.CODE if enrolled else Stage.ENROL


@dataclass(frozen=True)
class SessionFacts:
    stage: Stage
    created_at: datetime
    last_seen_at: datetime
    step_up_at: datetime | None
    ended: bool
    operator_active: bool


def session_refusal(s: SessionFacts, *, now: datetime, step_up: bool = False) -> str | None:
    """Why a full session may not act now, or None."""
    if s.ended or not s.operator_active:
        return "signed out"
    if now - s.created_at > ABSOLUTE_LIMIT or now - s.last_seen_at > IDLE_LIMIT:
        return "session expired"
    if s.stage is not Stage.FULL:
        return "sign-in not finished"
    if step_up and (s.step_up_at is None or now - s.step_up_at > STEP_UP_WINDOW):
        return "enter a fresh authenticator code"
    return None


def after_failure(failures: int, *, now: datetime) -> tuple[int, datetime | None]:
    """Failed attempts so far and, on the last allowed one, when the lock ends.
    The count restarts once a lock is set."""
    failures += 1
    return (0, now + LOCK_FOR) if failures >= MAX_FAILURES else (failures, None)


def password_refusal(password: str, *, email: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"use at least {MIN_PASSWORD} characters"
    local = email.split("@", 1)[0].lower()
    if len(local) >= 3 and local in password.lower():
        return "do not use your email in your password"
    return None
