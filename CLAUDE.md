# Wepl_fin

The WEPL money core: a register of who owns what in each group's pooled money,
the mandates that authorise payouts, and reconciliation against the custodian.

- **Standing rules:** `docs/architecture/engineering-guidelines.md` (Harry's
  60 guidelines). They override convenience. An ADR is the only way to depart
  from them.
- **Start here:** `docs/architecture/overview.md`, then `docs/adr/`.
- **Skills:** `.claude/skills/`:
  - `wepl-architecture`: where code goes;
  - `wepl-ledger`: money rules;
  - `wepl-custody`: statements, matching, reconciliation;
  - `wepl-testing`: how to prove it.
- **Commands:** run everything from `backend/`:
  - `python manage.py test`
  - `python manage.py makemigrations --check --dry-run`
  - `python manage.py demo_im_pilot`
- **Database:** tests need PostgreSQL 16; never sqlite.
