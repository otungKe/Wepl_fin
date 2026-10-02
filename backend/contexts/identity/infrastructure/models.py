from django.db import models

from contexts.tenancy.contract import TenantScope


class Person(models.Model):
    """A person, known by phone number, who may belong to groups in several
    tenants. USER_SCOPED (ADR-0009): it belongs to the person, not a tenant;
    tenants see a person only through a membership."""

    tenant_scope = TenantScope.USER_SCOPED
    msisdn = models.CharField(max_length=12, unique=True)
    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
