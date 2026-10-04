"""Operations context.

Owns: what WEPL's operators see and when the scheduled jobs run: the
operator inbox (every open problem in every group, read group by group),
the daily digest that tells operators whether the night's jobs ran and what
is open, and the nightly run that drives the other contexts' jobs in order.

Does not own: the problems themselves (custody alerts and reconciliations,
ledger integrity checks stay where they are raised), who is told inside a
group (notifications), or resolving anything: operators act through the
owning context.

Public surface: ``contexts.operations.public``.
"""
