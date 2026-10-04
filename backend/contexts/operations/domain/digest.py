"""The daily digest for WEPL operators. Pure Python.

It goes by email, which is not a private channel, so it carries counts by
group and kind and the outcome of each job, never a member's name, phone or
the alert text. The detail is in the operator inbox on the server."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .inbox import InboxItem, ItemKind


@dataclass(frozen=True)
class StepOutcome:
    name: str
    ok: bool
    note: str = ""  # a short summary, never personal data


def subject(steps: list[StepOutcome], items: list[InboxItem]) -> str:
    failed = [s.name for s in steps if not s.ok]
    urgent = sum(i.urgent for i in items)
    if failed:
        head = f"JOBS FAILED ({', '.join(failed)})"
    elif urgent:
        head = f"{urgent} URGENT"
    else:
        head = "all clear" if not items else f"{len(items)} open"
    return f"WEPL nightly: {head}"


def body(steps: list[StepOutcome], items: list[InboxItem]) -> str:
    lines = ["Nightly jobs:"]
    lines += [f"  {'ok    ' if s.ok else 'FAILED'} {s.name}{f': {s.note}' if s.note else ''}" for s in steps]
    if not items:
        lines += ["", "Nothing is open."]
        return "\n".join(lines) + "\n"
    urgent_groups = sorted({i.group for i in items if i.urgent})
    if urgent_groups:
        lines += ["", "URGENT: phone the officials of " + ", ".join(urgent_groups) + "."]
    lines += ["", "Open, by group:"]
    by_group = Counter((i.group, i.kind) for i in items)
    for group in sorted({g for g, _ in by_group}):
        kinds = ", ".join(f"{by_group[(group, k)]} {k.value}" for k in ItemKind if by_group[(group, k)])
        lines.append(f"  {group}: {kinds}")
    lines += ["", "Details: python manage.py operator_inbox"]
    return "\n".join(lines) + "\n"
