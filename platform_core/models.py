from django.db import models


class AuditEvent(models.Model):
    """Who did what, when and why. Append-only: a database trigger rejects
    UPDATE and DELETE (see migration 0002)."""

    actor = models.CharField(max_length=120)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=64)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]


class OutboxEvent(models.Model):
    """A side effect to perform after the transaction that caused it commits.

    Written in the same transaction as the business change, so an event exists
    if and only if the change committed. ``deliver_outbox`` performs them."""

    topic = models.CharField(max_length=80)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["delivered_at", "id"])]
