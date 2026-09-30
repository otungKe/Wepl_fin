from django.db import models

from ..domain.scope import TenantScope


class Tenant(models.Model):
    """Who a set of tenant-scoped rows belongs to. For the pilot, one tenant
    per group (ADR-0009)."""

    tenant_scope = TenantScope.SYSTEM
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
