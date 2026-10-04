from django.db import models

from contexts.tenancy.contract import TenantScope


class Operator(models.Model):
    """A member of WEPL's staff. SYSTEM scope (ADR-0009): operators belong to
    the platform, never to a tenant, and are never members (ADR-0021)."""

    tenant_scope = TenantScope.SYSTEM
    email = models.CharField(max_length=254, unique=True)  # stored lower-case
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=20)
    active = models.BooleanField(default=True)
    password = models.CharField(max_length=256)  # a Django password hash, never the password
    must_change_password = models.BooleanField(default=True)
    authenticator = models.BinaryField(null=True, editable=False)  # the TOTP secret, encrypted
    enrolled_at = models.DateTimeField(null=True)
    last_code_step = models.BigIntegerField(null=True)  # a code is accepted once
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(email=models.functions.Lower("email")),
                                              name="operators_email_lower_case")]


class OperatorSession(models.Model):
    """One sign-in. The browser holds a random token; only its hash is kept,
    so a copy of the database cannot be used to sign in."""

    tenant_scope = TenantScope.SYSTEM
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name="sessions")
    token_hash = models.CharField(max_length=64, unique=True)
    stage = models.CharField(max_length=20)
    pending_authenticator = models.BinaryField(null=True, editable=False)  # during enrolment, encrypted
    created_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    step_up_at = models.DateTimeField(null=True)
    ended_at = models.DateTimeField(null=True)


class OperatorEvent(models.Model):
    """The sign-in log: append-only (operators 0001). Outside any tenant, so
    it is kept here rather than in the tenant-scoped audit trail."""

    tenant_scope = TenantScope.SYSTEM
    operator = models.ForeignKey(Operator, null=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=60)
    actor = models.CharField(max_length=120)  # who did it: the operator, another operator, or the server
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
