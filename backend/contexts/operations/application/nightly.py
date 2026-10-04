"""The nightly run: each context's job in order, then the digest.

A job that fails does not stop the ones after it: the books are still
checked when a bank is unreachable, and the digest always goes out saying
what failed. Each job is the context's own management command, so it can
also be run by hand."""
import io

from django.core.management import call_command

from ..domain.digest import StepOutcome
from .digest import send_digest
from .inbox import operator_inbox

STEPS = (
    ("sync_accounts", "fetch bank activity and reconcile every account"),
    ("check_ledger_integrity", "check every fund's books"),
    ("deliver_outbox", "send queued messages"),
)


def run_nightly() -> tuple[list[StepOutcome], str]:
    steps = [_run(name) for name, _ in STEPS]
    try:
        items = operator_inbox(actor="system")
    except Exception as exc:  # the digest must still go out
        steps.append(StepOutcome("operator_inbox", False, type(exc).__name__))
        items = []
    return steps, send_digest(steps, items)


def _run(name: str) -> StepOutcome:
    out, err = io.StringIO(), io.StringIO()
    try:
        call_command(name, stdout=out, stderr=err)
    except Exception as exc:  # SystemExit is not caught: an interrupted run is not a result
        return StepOutcome(name, False, _last_line(err) or type(exc).__name__)
    problems = _last_line(err)
    return StepOutcome(name, not problems, problems or _last_line(out))


def _last_line(buffer: io.StringIO) -> str:
    lines = [l for l in buffer.getvalue().splitlines() if l.strip()]
    return lines[-1][:120] if lines else ""
