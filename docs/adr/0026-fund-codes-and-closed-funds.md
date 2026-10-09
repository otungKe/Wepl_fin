# ADR-0026: A fund code means one fund for good; a closed fund takes no money

- **Status:** **Accepted** (Harry, 2026-10-06: "all your recommendation", on
  the Communities review of 2026-10-06, decisions D1–D5).
- **Touches:** ADR-0015 (fund lifecycle), ADR-0019 (the collections
  reference), ADR-0021 (operator roles), ADR-0023 (one account holds the
  group's funds), ADR-0025 (moving a pay-in).

## Context

The Communities review of 2026-10-06
(`/mnt/project-files/wepl-fin-reviews/communities-review-2026-10-06.md`)
found:

- **A fund could close while holding money.** `close_fund` locks the fund and
  asks the ledger whether it holds anything; a pay-in quoting the fund's code
  took no lock on the fund, so both could commit. Reproduced: a closed fund
  holding KES 500 that no proposal or transfer could pay out. ADR-0015 relied
  on "every posting comes through a linked account, and a closed fund has
  none"; ADR-0023 voided that, since one account holds every fund.
- **A fund code was free for reuse as soon as it changed**, or its fund
  closed, so a payer quoting an old code could pay into a different fund.
- **Status values were not checked** by PostgreSQL, so a raw write of a third
  value stepped around "left is final" and around the close guards.
- **"Default fund"** read as a Communities concept. It is custody's: the
  fund a bank account was linked with (ADR-0023).

## Decision

1. **D1. The default fund stays, and it is custody's.** Communities has no
   default fund: a group is founded with none, and funds are 0..n (ADR-0013).
   Custody's default fund (`ExternalAccount.fund`) takes what ADR-0023 says
   it takes. Communities' text says so.
2. **D2. A fund code is its fund's for good.** PostgreSQL records every code
   a fund takes (`communities_fundcode`, append-only) and refuses a code
   another fund of the group ever held, including a closed fund's. The fund
   itself may take an old code back. Codes used before this were reserved
   from the funds and the audit trail, earliest first (communities 0017–0018).
3. **D3. Groups, members and funds are set up by operators** holding
   `groups.setup` (the onboarding and admin roles, ADR-0021), with a fresh
   authenticator code. This covers founding a group, adding a member or
   recording that they left, and opening, renaming, coding or closing a fund.
   The commands keep their `actor` until an endpoint calls them; that
   endpoint takes the operator from `operators.public.authenticate` and
   audits `operator:<id>`.
4. **D4. An unclear fund code raises an alert.** A pay-in whose reference
   quotes letters that are no open fund's code, or the codes of two different
   funds, goes to the default fund as before, and custody raises a
   `fund_code_unclear` alert. A corrector settles it: `move_pay_in` (ADR-0025)
   or `keep_pay_in(line, by, reason)`, which confirms it stays and posts
   nothing. A reference naming exactly one fund is clear. The collections
   check refuses both cases before payment. The code that routed a pay-in is
   kept in its line resolution's note.
5. **D5. Codes are three to six letters**, so fewer ordinary words a payer
   types are read as one.
6. **A closed fund takes no money.** Every journal entry reads its fund
   `FOR SHARE` and is refused if the fund is closed (communities 0019).
   `close_fund` locks the fund `FOR UPDATE` first, so the two serialise:
   - a posting first: closing waits, then finds the money and refuses;
   - closing first: the posting waits, then is refused.

   Ingestion also locks the fund a code routes to (`hold_open_fund`) and
   routes again if it closed meanwhile, so the line is not lost: it goes to
   the default fund with an alert.
7. **Status values are checked:** a fund is `open` or `closed`, a membership
   `active` or `left`. A spell ends no earlier than it began; an ended
   spell's title never changes; a group never moves to another tenant
   (communities 0016).

## Alternatives

- **No default fund; hold uncoded money unassigned.** Needs a new place in
  the ledger for money that belongs to no fund, and replaces ADR-0023 §3–5.
  Not chosen (D1).
- **Codes reusable after a waiting period.** Still misroutes a late payer.
- **Check fund status in the ledger.** The ledger reads no other context
  (ADR-0004); the rule sits on the Communities side, as 0013 already does.

## Consequences

- A group that wants a code back for a new pool must keep the old fund's
  meaning: the new fund needs a new code.
- Two-letter codes are refused from now on. A database already holding one
  stops at migration 0017 until that fund is given a longer code; there is no
  production data yet.
- Fund-code alerts count as open alerts, so an account cannot close until
  they are settled (ADR-0015 addendum).
- A posting into a fund waits while that fund is being closed. Postings into
  the same open fund never wait on each other.
