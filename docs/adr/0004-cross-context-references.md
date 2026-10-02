# ADR-0004: How contexts refer to each other's records

- **Status:** Proposed (2026-09-30)

## Context

Rule 4 forbids reaching into another context's models for convenience, but
allows deliberate, documented foreign keys.

## Decision

- **No code imports another context's models.** Other contexts are reached only
  through `public.py` and `contract.py`.
- **The ledger holds plain ids**, not foreign keys. It is the foundation and
  must not depend on any other context's tables.
- **The foreign keys below are declared by string** (for example
  `"communities.Membership"`), with `on_delete=PROTECT`. Each one records a
  real domain relationship to a row that is never deleted, so the database
  keeps referential integrity without creating code coupling.

| From | To | Why |
|---|---|---|
| communities.Membership.person | identity.Person | A membership is a person's relationship with a group |
| governance.* group, fund | communities.Group, Fund | Rules, proposals and mandates exist within a group and fund |
| governance.* proposed_by, charged_member, membership | communities.Membership | Who proposed, who is charged, who voted |
| custody.ExternalAccount group, fund | communities.Group, Fund | The account holds that fund's money |
| custody.LineResolution membership, mandate | communities.Membership, governance.Mandate | The accounting decision names who paid or which mandate authorised it |
| custody.PayerMapping membership | communities.Membership | A remembered payer is a member |

Governance stores the custody statement line that executed a mandate as a
plain id (`executed_by_line_id`), which keeps governance independent of
custody.

## Consequences

- Extracting a context into its own service later would turn these keys into
  ids plus integration contracts. The list above is the work list for that.
- Migrations of a referencing context depend on the referenced context's
  migrations, which Django orders automatically.
