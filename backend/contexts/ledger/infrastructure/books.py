"""The integrity check's own reading of the books (ledger 0010).

Plain SQL over the journal tables, sharing nothing with the balance queries
in ``application/queries.py``, so a bug there cannot make the check agree
with it. It runs under the caller's tenant context like every other read."""
from decimal import Decimal

from django.db import connection

from ..domain.transfer import TRANSFER_IN, TRANSFER_OUT

_TOTALS = """
SELECT a.purpose, coalesce(sum(l.amount) FILTER (WHERE l.side = 'D'), 0),
       coalesce(sum(l.amount) FILTER (WHERE l.side = 'C'), 0), count(*)
  FROM ledger_journalline l JOIN ledger_account a ON a.id = l.account_id
 WHERE a.fund_id = %s AND a.currency = %s
 GROUP BY a.purpose
"""

# An entry of the fund breaks the posting rules if it has fewer than two
# lines, a line on another fund's account, or lines that do not balance in
# some currency: what 0002 and 0005 refuse, entry by entry.
_BROKEN = """
SELECT count(*) FROM (
    SELECT entry_id FROM (
        SELECT e.id AS entry_id, count(l.id) AS n,
               coalesce(sum(CASE l.side WHEN 'D' THEN l.amount ELSE -l.amount END), 0) AS net,
               bool_and(a.fund_id IS NULL OR a.fund_id = e.fund_id) AS in_fund
          FROM ledger_journalentry e
          LEFT JOIN ledger_journalline l ON l.entry_id = e.id
          LEFT JOIN ledger_account a ON a.id = l.account_id
         WHERE e.fund_id = %s
         GROUP BY e.id, a.currency) per_currency
     GROUP BY entry_id
    HAVING sum(n) < 2 OR bool_or(net <> 0) OR NOT bool_and(in_fund)) broken
"""

# A transfer leg is paired when its cause has exactly two legs and the other
# kind is in another fund (ADR-0024). One query, using the cause index.
_UNPAIRED = """
SELECT count(*) FROM ledger_journalentry e
 WHERE e.fund_id = %(fund)s AND e.kind IN (%(out)s, %(in)s)
   AND ((SELECT count(*) FROM ledger_journalentry o
          WHERE o.cause_type = e.cause_type AND o.cause_id = e.cause_id AND o.kind IN (%(out)s, %(in)s)) <> 2
        OR (SELECT count(*) FROM ledger_journalentry o
             WHERE o.cause_type = e.cause_type AND o.cause_id = e.cause_id AND o.kind IN (%(out)s, %(in)s)
               AND o.kind <> e.kind AND o.fund_id <> e.fund_id) <> 1)
"""


def _one(sql: str, params) -> int:
    with connection.cursor() as c:
        c.execute(sql, params)
        return c.fetchone()[0]


def totals_by_purpose(fund_id: int, currency: str) -> tuple[dict[str, tuple[Decimal, Decimal]], int]:
    """(debits, credits) per account purpose, and the number of lines."""
    with connection.cursor() as c:
        c.execute(_TOTALS, [fund_id, currency])
        rows = c.fetchall()
    return {purpose: (debits, credits) for purpose, debits, credits, _ in rows}, sum(n for *_, n in rows)


def broken_entries(fund_id: int) -> int:
    return _one(_BROKEN, [fund_id])


def unpaired_transfers(fund_id: int) -> int:
    return _one(_UNPAIRED, {"fund": fund_id, "out": TRANSFER_OUT, "in": TRANSFER_IN})
