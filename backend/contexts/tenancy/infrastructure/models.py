from django.db import models

from ..domain.scope import TenantScope


class Tenant(models.Model):
    """An independently governed data boundary: one group (ADR-0010).
    Institutions are relationships to tenants, never tenants by default."""

    tenant_scope = TenantScope.SYSTEM
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
