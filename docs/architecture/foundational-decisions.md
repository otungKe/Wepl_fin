# Foundational decisions

Set by Harry on 2026-09-30, verbatim. Like the
[engineering guidelines](engineering-guidelines.md), these are standing rules;
an ADR is the only way to depart from them. ADR-0001 (Django) and ADR-0009
(tenancy) record how the code implements them.

## 1. Django Version

The rebuild uses Django 5.2 LTS as the backend framework baseline.
Do not upgrade to Django 6.0 merely because it is newer.
The reasons for choosing Django 5.2 LTS are:

* long-term security/support lifecycle
* stability for a new foundational architecture
* mature third-party ecosystem compatibility
* reduced upgrade pressure during the early rebuild
* the ability to move to a later Django release deliberately once the system architecture is stable

Use the latest appropriate 5.2.x patch release, not an arbitrary early 5.2 release.
Django itself recommends using stable releases in production and provides backwards-compatible bug/security releases within a release series.
If a requirement appears to require Django 6.0, do not silently switch versions.
Instead:

1. identify the specific 6.0 capability;
2. determine whether it is genuinely required;
3. determine whether 5.2 has an acceptable implementation;
4. document the decision in an ADR if the requirement materially affects the architecture.

The framework version must never dictate the domain architecture.

## 2. Tenancy Architecture

WEPL is a multi-tenant system.
Tenant isolation is a security and architectural boundary.
The tenancy model is:

```text
Application Tenant Context
        ↓
Application-level authorization/scoping
        ↓
PostgreSQL Row-Level Security
        ↓
Physical database enforcement
```

Application-level tenant filtering is NOT considered sufficient isolation by itself.
PostgreSQL RLS is the final database-level enforcement mechanism for tenant-scoped data.
Where appropriate, tenant tables should use:

* Row-Level Security
* FORCE ROW LEVEL SECURITY
* explicit tenant context
* database policies
* tenant-isolation integration tests

## 3. Tenant Context

Tenant context must be explicit.
Every operation involving tenant-scoped data must have an identifiable tenant context.
Do not silently derive tenant identity from arbitrary request/model relationships.
The system should be able to answer:
Which tenant is this operation executing for?
at every point where tenant-scoped state is accessed.

## 4. Tenant Scope Classification

Every persistent domain concept must be deliberately classified as one of:

```text
GLOBAL
TENANT_SCOPED
USER_SCOPED
SYSTEM/CROSS_TENANT
```

Do not automatically make every model tenant-scoped.
Do not automatically make every model global.
The classification must follow the domain.
Document unusual cases.

## 5. Tenant Isolation

A tenant-scoped operation must satisfy BOTH:

```text
application-level authorization/scoping
+
database-level RLS enforcement
```

Do not rely on developers remembering:

```python
.filter(tenant=tenant)
```

as the fundamental security boundary.
That is a developer convenience and query discipline.
RLS is the defensive boundary.

## 6. Cross-Tenant Operations

Cross-tenant access is exceptional.
It must be:

* explicit
* authorized
* auditable
* intentional

Do not create APIs or repository methods that accidentally make unrestricted cross-tenant access convenient.
A system-level operation must clearly declare that it is operating outside a tenant boundary.

## 7. Background Workers

Celery/background workers do not automatically inherit HTTP request context.
Every tenant-scoped background operation must establish its tenant context explicitly.
Tenant context must also be cleared after execution.
A worker must never accidentally reuse the tenant context of a previous task.

## 8. Database Access

The database must be treated as part of the security architecture.
For tenant-scoped data:

```text
application query
       ↓
tenant context
       ↓
PostgreSQL RLS policy
       ↓
database result
```

The application must not attempt to circumvent RLS merely because a privileged operation is convenient.
If a legitimate system operation requires broader access, that access must be explicit and controlled.

## 9. Contexts and Tenancy

Bounded contexts remain the primary business architecture.
Tenancy does NOT replace bounded contexts.
For every context ask separately:

1. What business capability does this context own?
2. What data does it own?
3. Is that data global or tenant-scoped?
4. What tenant relationship does the domain actually require?
5. What does the context expose to other contexts?

Do not create artificial domain boundaries merely because tenancy exists.

## 10. No "Tenant App"

Do not create a single generic "tenancy layer" and push all business logic through it.
Tenancy provides a cross-cutting security/infrastructure capability.
Business contexts remain responsible for their own domain behavior.
For example:

```text
Ledger
    owns financial rules

Contributions
    owns contribution rules

Communities
    owns community rules

Tenancy
    owns tenant lifecycle/context/isolation mechanisms
```

These responsibilities must remain distinct.

## 11. Architectural Priority

The rebuild priorities are:

```text
1. Domain correctness
2. Bounded-context ownership
3. Financial integrity
4. Tenant isolation
5. Security
6. Explicit application workflows
7. Testability
8. Observability
9. Performance
10. Framework convenience
```

Do not reverse this order merely to make implementation easier.

## 12. Framework Independence of the Domain

Django 5.2 is the current implementation framework.
It is not the definition of WEPL's architecture.
The domain should remain conceptually understandable without knowing:

* Django
* DRF
* PostgreSQL
* Celery
* Redis
* M-Pesa
* any other external provider

Infrastructure implements the requirements of the domain.
The domain does not exist to satisfy infrastructure limitations.
