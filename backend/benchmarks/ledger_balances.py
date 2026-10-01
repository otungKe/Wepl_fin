"""How long derived balances take as a fund's history grows (ADR-0016).

Balances are never stored: every read sums the fund's journal lines. This
measures each ledger read, and one posting, at fund sizes from a typical
group's year up to far beyond any pilot group, in a database that also holds
other tenants' history.

Run from backend/, against a scratch database (never the real one):

    createdb wepl_bench && DB_NAME=wepl_bench python manage.py migrate
    DB_NAME=wepl_bench BENCH_ADMIN_DSN="host=/tmp user=postgres dbname=wepl_bench" \\
        python benchmarks/ledger_balances.py

History is bulk-loaded by a superuser with triggers off (posting a million
entries one by one would take hours). The rows are balanced by construction,
and the script checks that afterwards. Every measurement then runs as the
application role, under row-level security, through the ledger's public reads.
"""
import os
import statistics
import sys
import time

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import psycopg  # noqa: E402
from django.conf import settings  # noqa: E402

from contexts.communities.infrastructure.models import Fund  # noqa: E402  (finding the bench's own funds)
from contexts.communities.public import create_group, open_fund  # noqa: E402
from contexts.ledger.public import (AccountKey, AccountPurpose, JournalDraft, Side, account_balance,  # noqa: E402
                                    fund_holds_nothing, fund_position, member_balances, member_movements,
                                    post_journal, trial_balance)
from contexts.shared_kernel.money import Money  # noqa: E402
from contexts.tenancy.public import cross_tenant, tenant  # noqa: E402

# (label, journal entries, members). Two lines per entry, as custody posts;
# one entry per contribution, plus one payout in ten. Labels are the group
# that would produce that history (ADR-0016).
FUNDS = [
    ("30 members monthly, 1 year", 400, 30),
    ("200 members weekly, 11 months", 10_000, 200),
    ("500 members weekly, 3.5 years", 100_000, 500),
    ("1,000 members weekly, 17 years", 1_000_000, 1_000),
]
# Other tenants' history in the same tables: "tenants,entries,members" per
# batch. Batches add up, so a second run with another batch grows the platform
# while keeping the measured funds.
BACKGROUND = os.environ.get("BENCH_BACKGROUND", "50,20000,50")
RUNS = 7


def load(admin, tenant_id, group_id, fund_id, entries, members, cash_ext):
    """Insert a fund's accounts and `entries` balanced two-line entries:
    nine in ten are receipts (cash D / member C), one in ten a payout."""
    with admin.cursor() as c:
        c.execute("SET session_replication_role = replica")
        c.execute("""
            INSERT INTO ledger_account (tenant_id, purpose, group_id, fund_id, member_id, external_account_id,
                                        currency, normal_side, created_at)
            SELECT %(t)s, 'custody_cash', %(g)s, %(f)s, NULL, %(x)s, 'KES', 'D', now()
            UNION ALL
            SELECT %(t)s, 'member_interest', %(g)s, %(f)s, m, NULL, 'KES', 'C', now()
            FROM generate_series(1, %(m)s) m""", {"t": tenant_id, "g": group_id, "f": fund_id, "x": cash_ext,
                                                   "m": members})
        c.execute("""
            WITH e AS (
                INSERT INTO ledger_journalentry (tenant_id, idempotency_key, fingerprint, group_id, fund_id, kind,
                                                 memo, cause_type, cause_id, operation_id, created_at)
                SELECT %(t)s, 'bench:' || %(f)s || ':' || n, '', %(g)s, %(f)s,
                       CASE WHEN n %% 10 = 0 THEN 'payout' ELSE 'receipt' END, '', 'bench', n::text, '', now()
                FROM generate_series(1, %(n)s) n
                RETURNING id, cause_id::int AS n)
            INSERT INTO ledger_journalline (tenant_id, entry_id, account_id, side, amount)
            SELECT %(t)s, e.id, a.id,
                   CASE WHEN (e.n %% 10 = 0) = (a.purpose = 'custody_cash') THEN 'C' ELSE 'D' END,
                   CASE WHEN e.n %% 10 = 0 THEN 50 ELSE 100 + e.n %% 900 END
            FROM e JOIN ledger_account a ON a.fund_id = %(f)s AND a.tenant_id = %(t)s
                 AND (a.purpose = 'custody_cash' OR a.member_id = 1 + e.n %% %(m)s)""",
                  {"t": tenant_id, "g": group_id, "f": fund_id, "n": entries, "m": members})
        c.execute("SET session_replication_role = origin")
    admin.commit()


def new_fund(name):
    group = create_group(name, actor="bench")
    with tenant(group.tenant_id):
        fund = open_fund(group.id, name="Main savings", actor="bench")
    return group, fund


def existing_fund(name):
    with cross_tenant("benchmark: find a fund loaded earlier", actor="bench"):
        found = Fund.objects.filter(group__name=name).select_related("group").first()
    return (found.group, found) if found else None


def platform_size(admin):
    with admin.cursor() as c:
        c.execute("SELECT (SELECT count(*) FROM ledger_journalline), (SELECT count(*) FROM ledger_journalentry), "
                  "(SELECT count(*) FROM ledger_account), (SELECT count(*) FROM tenancy_tenant)")
        return c.fetchone()


def timed(fn):
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def main():
    dsn = os.environ.get("BENCH_ADMIN_DSN")
    if not dsn or settings.DATABASES["default"]["NAME"] in ("wepl", "test_wepl"):
        sys.exit("Set DB_NAME to a scratch database and BENCH_ADMIN_DSN to a superuser connection to it.")
    admin = psycopg.connect(dsn)

    tenants, entries_each, members_each = (int(v) for v in BACKGROUND.split(","))
    batch = time.strftime("%H%M%S")
    print(f"Loading {tenants} background tenants x {entries_each} entries...", flush=True)
    for n in range(tenants):
        g, f = new_fund(f"Background {batch}-{n}")
        load(admin, g.tenant_id, g.id, f.id, entries_each, members_each, 800_000 + f.id)
    measured = []
    for label, entries, members in FUNDS:
        found = existing_fund(label)
        if not found:
            print(f"Loading {label}: {entries} entries...", flush=True)
            found = new_fund(label)
            load(admin, found[0].tenant_id, found[0].id, found[1].id, entries, members, 900_000 + found[1].id)
        measured.append((label, entries, members, *found))
    with admin.cursor() as c:
        c.execute("ANALYZE")
    admin.commit()

    lines, entries, accounts, tenants = platform_size(admin)
    print(f"\nPlatform: {lines:,} journal lines, {entries:,} entries, {accounts:,} accounts, {tenants:,} tenants\n")
    print("| Fund | Lines | Members | fund_position | member_balances | account_balance (cash) "
          "| trial_balance(fund) | fund_holds_nothing | member_movements | post_journal |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for label, entries, members, g, f in measured:
        with tenant(g.tenant_id):
            cash = AccountKey(group_id=g.id, fund_id=f.id, purpose=AccountPurpose.CUSTODY_CASH,
                              external_account_id=900_000 + f.id)
            pos = fund_position(f.id)
            assert pos.invariant_holds and trial_balance(f.id) == 0, "loaded history does not balance"
            assert len(member_balances(f.id)) == members
            member = AccountKey(group_id=g.id, fund_id=f.id, purpose=AccountPurpose.MEMBER_INTEREST, member_id=1)
            counter = iter(range(10 ** 6))
            run = time.time_ns()

            row = [timed(lambda: fund_position(f.id)), timed(lambda: member_balances(f.id)),
                   timed(lambda: account_balance(cash)), timed(lambda: trial_balance(f.id)),
                   timed(lambda: fund_holds_nothing(f.id)), timed(lambda: member_movements(f.id, 1))]

        def post():  # its own transaction, so the commit-time balance check is included
            with tenant(g.tenant_id):
                post_journal(JournalDraft.build(
                    idempotency_key=f"bench-post-{run}-{next(counter)}", group_id=g.id, fund_id=f.id, kind="receipt",
                    cause_type="bench", cause_id="x", postings=[(cash, Side.DEBIT, Money("100")),
                                                                 (member, Side.CREDIT, Money("100"))]))
        row.append(timed(post))
        print(f"| {label} | {entries * 2:,} | {members:,} | " + " | ".join(f"{ms:,.1f} ms" for ms in row) + " |")


if __name__ == "__main__":
    main()
