# ADR-0001: Stack

- **Status:** Proposed (2026-09-28)
- **Decider:** Harry

## Context

Wepl serves small, unbanked groups that exist all year (chamas, welfare
committees, workplace groups) and collect money on cycles the group sets. Most
members pay from any phone with an M-Pesa SIM; the treasurer and chair run the
group, usually from a smartphone. The first milestone is a working MVP for an
investor presentation, then real groups.

The team is Harry plus Claude. What the first Wepl taught us about stack:

- **Four codebases were too many.** Django API, an Expo app, a Next.js customer
  web app and a Next.js ops console, with about 243 TypeScript types copied by
  hand from the API. Every feature was built up to four times.
- **The ledger was the best part**, and it is Python and Postgres: `Decimal`
  money, a deferred trigger that checks every journal balances at commit, and
  triggers that make journals immutable. That knowledge should carry over.
- **Celery and Redis cost more than they gave.** On Render's free tier they ran
  inside the web process, and a scheduled job (standing orders) failed silently
  for weeks.
- **Members do not need an app.** STK push and paybill work on any phone.
  Receipts and reminders by SMS reach everyone.

## Decision

One language, one codebase, one deployable, until real use proves otherwise.

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| Framework | Django 6.0, server-rendered HTML |
| Interactivity | HTMX for partial updates; no single-page app |
| Installable app | A Progressive Web App (installs from the browser, no store) |
| Database | PostgreSQL 16 on Neon; money rules enforced in the database too |
| Background work | A Postgres outbox, delivered after commit, with a scheduled sweep for retries. No Redis, no Celery |
| Payments | M-Pesa Daraja behind a provider port; a fake provider for tests and demos |
| Member channel | SMS (Africa's Talking) behind a port; USSD later on the same port |
| Auth | Phone number plus one-time code, Django sessions |
| Hosting | Render web service plus one cron job; Neon database |
| Tests and CI | Django test runner on real Postgres, GitHub Actions |

## Alternatives considered

- **Django API plus a Next.js or React Native front end.** Better app feel,
  but two codebases and the type-copying problem again. Revisit if a native
  app is ever the thing users ask for.
- **All TypeScript (Next.js with Prisma or Drizzle).** One language, and many
  hires know it, but decimal money and database-enforced ledger rules are
  weaker there, and we would rewrite what we already know works.
- **Celery and Redis from day one.** Not needed until work cannot finish inside
  a request plus a scheduled sweep.

## Consequences

- One person can change a screen, its rules and its tests in one commit.
- The UI is simpler than a native app. For an investor demo, a fast, clean
  mobile web app on a phone is enough; it can be installed to the home screen.
- If a native app becomes necessary, Django can add a JSON API next to the
  HTML views without moving any rules, because rules live in services, not views.
- Scheduled work runs from a Render cron job calling a management command, so
  it is visible in logs and cannot fail silently inside the web process.
