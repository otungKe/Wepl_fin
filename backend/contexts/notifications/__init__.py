"""Notifications context.

Owns: messages the system has decided to send (the outbox), and delivering
them through a notifier (SMS, email, in-app). Queued in the same transaction
as the business change that caused them, delivered at least once afterwards.

Does not own: deciding *whether* something is worth telling people (the
context where it happened decides), or who belongs to a group.

SMS is on hold while a provider is chosen; the default notifier logs.

Public surface: ``contexts.notifications.public``.
"""
