from django.db import models

from contexts.tenancy.contract import TenantScope
from persistence.tenancy import tenant_column


class AuditEvent(models.Model):
    """Append-only (enforced by a database trigger)."""

    tenant_scope = TenantScope.TENANT_SCOPED
    tenant = tenant_column()
    actor = models.CharField(max_length=120)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60)
    target_id = models.CharField(max_length=64)
    group_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    operation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]
