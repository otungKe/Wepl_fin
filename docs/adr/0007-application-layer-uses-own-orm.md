# ADR-0007: Shortcut — application code uses its own context's ORM models

- **Status:** Proposed; a deliberate, visible shortcut (rule 42)

## What the shortcut is

Rule 7 prefers that application code reach persistence through ports
implemented by infrastructure. Here, each context's `application` modules use
that context's own Django models directly, except the ledger's account
resolution, which sits in `infrastructure/accounts.py`.

## Why

- Every business rule already lives in the pure `domain` package and is
  tested without a database.
- Application modules only load facts, call the domain and save the result.
- A repository layer over each model would add code without a second
  implementation to justify it (rule 41).

## Consequence

Application code depends on Django's ORM, so it cannot run without a database.
The domain can, and that is where the rules are.

**The boundary still holds.** No context touches another context's models;
the architecture test enforces this.

## What would make us revisit

Any of these:
- a second persistence implementation is needed (for example an event store,
  or extracting a context);
- application modules start carrying rules that belong in the domain;
- tests of use cases become slow enough to need in-memory fakes.
