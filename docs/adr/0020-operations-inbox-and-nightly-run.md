# ADR-0020: The operator inbox, the daily digest and the nightly run

- **Status:** Proposed (2026-10-04). Harry asked for this step on
  2026-10-04 ("proceed as suggested"). The design is Claude's
  recommendation and is accepted only on Harry's word.
- **Touches:**
  - ADR-0002 (a new `operations` context);
  - ADR-0010 (WEPL's operators are not a tenant);
  - ADR-0016 (the nightly integrity check).

## Context

- **The jobs exist but nothing runs them.** `sync_accounts`,
  `check_ledger_integrity` and `deliver_outbox` all exist, but none is
  scheduled.
- **Alerts reach nobody.**
  - The SMS provider is on hold, so the outbox only logs.
  - Harry decided on 2026-09-28 that, until SMS exists, a WEPL operator
    phones a group's officials about urgent alerts.
  - So operators need one place that shows every open problem, and a way to
    know that the night's jobs ran.

## Decision

1. **A new `operations` context.** It owns the operator inbox, the daily
   digest and the nightly run. It owns no problem itself: alerts,
   reconciliations and integrity checks stay in custody and the ledger, and
   operators act through those contexts.
2. **The operator inbox** (`python manage.py operator_inbox --operator NAME`)
   lists every open problem in every group, urgent first, then oldest first:
   - an integrity check that failed (urgent);
   - money that left without a mandate (urgent);
   - a reconciliation difference;
   - a statement conflict;
   - an account not reconciled in the last 36 hours.

   It is a declared, audited job that acts for each tenant in turn, through
   each context's public surface. No query sees two groups at once.
3. **The nightly run** (`python manage.py nightly`):
   - runs sync and reconcile, then the integrity check, then delivery;
   - lets a failing job leave the others running;
   - exits non-zero if any job failed.
4. **The digest** goes to `WEPL_OPERATIONS_EMAIL` every night, even when
   nothing is open, so a missing email means the jobs did not run.
   - It carries the outcome of each job, counts by group and kind, and the
     groups whose officials must be phoned.
   - It never carries a member's name, a phone number or the alert text.
     Email is not a private channel; the detail stays in the inbox on the
     server.
5. **Boot guard.** A production configuration that names an operations
   address but whose email backend would not send refuses to start.

## Alternatives

- **Emailing every alert to group officials:** rejected. Their addresses
  are unverified, and the alert text names members and amounts.
- **A scheduler inside the app (Celery beat):** rejected by ADR-0001 (no
  Redis or Celery). The host's cron or systemd timer runs the command.

## Consequences

- **Scheduling** is a deployment step: see `docs/operations/nightly.md`.
- **Until login exists, the inbox is a server command.** Whoever can run it
  can see every group's alerts. The operator's name is recorded with each
  look.
- **A resolved alert leaves the inbox** once its owning context marks it
  resolved.
