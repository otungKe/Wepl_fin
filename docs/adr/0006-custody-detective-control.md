# ADR-0006: Pilot custody is detective; WEPL never holds money

- **Status:** Proposed (2026-09-30)

## Context

A Kenyan bank is the intended custodian and possible banking-as-a-service
provider (CONFIRMED: Harry, 2026-09-28). The custody options are set out in
`/mnt/project-files/wepl-custody/wepl-custody-design-im.md`.

## Decision

- **Pilot (Model A).** Each group holds its money in its own Chama Account at the custodian bank.
  Officials pay out in the bank's own channels, under its dual
  authorisation. WEPL reads the statement, attributes pay-ins, matches every
  payout to a governance mandate, alerts every member when there is no
  match, and reconciles to the cent.
- **Target (Model C).** The custodian bank's BaaS, where WEPL submits payouts and the mandate
  becomes a preventive control. That will be a new `payments` context behind
  a provider port. The mandate, matching and ledger rules do not change.
- Custodian integrations implement `custody.contract.Connector`. Which
  implementation is used for an account comes from settings, so no context
  imports an integration (rule 21). Provider detail stays in each line's
  `metadata` (rule 22).

## Consequences

- WEPL is not a money holder in the pilot (legal position to be confirmed:
  V8 in the pilot plan; UNKNOWN until counsel's written opinion).
- The real custodian statement format is UNKNOWN until a sample export arrives.
  Until then the simulator stands in.
