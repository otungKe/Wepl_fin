"""When contributions fall due under a fund's rule (ADR-0022)."""
from __future__ import annotations

from datetime import date, timedelta

from contexts.governance.contract import ContributionRule, Frequency, JoinersOweFrom


def due_dates(rule: ContributionRule, start: date, end: date) -> list[date]:
    """The rule's due dates from ``start`` to ``end``, both included, never
    before the rule's ``starts_on``."""
    start = max(start, rule.starts_on)
    out = []
    if rule.frequency is Frequency.WEEKLY:
        day = start + timedelta(days=(rule.due_day - start.isoweekday()) % 7)
        while day <= end:
            out.append(day)
            day += timedelta(days=7)
        return out
    year, month = start.year, start.month
    while (day := date(year, month, rule.due_day)) <= end:
        if day >= start:
            out.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def owed_from(rule: ContributionRule, joined_on: date) -> date:
    """The first day a member's spell can owe under the rule, as the group chose."""
    if rule.joiners_owe_from is JoinersOweFrom.START:
        return rule.starts_on
    return max(rule.starts_on, joined_on)


def periods(versions: list[tuple[date, ContributionRule | None]], *, joined_on: date, until: date,
            upcoming: bool) -> list[tuple[date, object]]:
    """Each due date of a spell, with its amount, from the rule in force on
    that date. ``versions`` is (in force from, the fund's rule or None),
    oldest first; the first covers everything before it. ``upcoming`` adds
    the next due date after ``until``, so a payment made before it counts
    for that period."""
    out = []
    for i, (since, rule) in enumerate(versions):
        if rule is None:
            continue
        lo = date.min if i == 0 else since
        hi = versions[i + 1][0] - timedelta(days=1) if i + 1 < len(versions) else date.max
        start = max(lo, owed_from(rule, joined_on))
        out += [(d, rule.amount) for d in due_dates(rule, start, min(hi, until))]
        if upcoming and hi > until and start <= hi:
            later = due_dates(rule, max(start, until + timedelta(days=1)), min(hi, until + timedelta(days=31)))
            out += [(d, rule.amount) for d in later[:1]]
    return out
