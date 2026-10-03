from django.db import models

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column


class OutboxEvent(models.Model):
    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    topic = models.CharField(max_length=80)
    payload = models.JSONField()
    dedupe_key = models.CharField(max_length=160, null=True, blank=True)  # unique per tenant
    operation_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    claimed_until = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        # notify() looks a dedupe key up with no tenant predicate; row-level
        # security's OR cannot enter the tenant-leading unique index, so
        # without this every alert scanned every tenant's outbox (ADR-0016).
        indexes = [models.Index(fields=["delivered_at", "id"]),
                   models.Index(fields=["dedupe_key"], name="outbox_dedupe_key")]
        constraints = [models.UniqueConstraint(fields=["tenant", "dedupe_key"], name="outbox_dedupe_key_unique")]
