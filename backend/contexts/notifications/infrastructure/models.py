from django.db import models


class OutboxEvent(models.Model):
    topic = models.CharField(max_length=80)
    payload = models.JSONField()
    dedupe_key = models.CharField(max_length=160, null=True, blank=True, unique=True)
    operation_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["delivered_at", "id"])]
