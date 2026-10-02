# WEPL Rebuild — General Architecture & Engineering Guidelines

> Set by Harry on 2026-09-30. Text as given; only markdown headings were added.

These are the standing architectural and engineering rules for the WEPL rebuild.
They apply across the entire codebase unless an explicit ADR supersedes them.

## 1. Start With the Domain, Not Django

WEPL is a business/domain system implemented using Django.
Do not allow Django's default concepts — `apps`, models, serializers, views, signals, or admin — to determine the business architecture.
The domain determines the architecture.
Before creating a module, model, service, API, or database table, ask:

1. What business capability does this belong to?
2. Which bounded context owns that capability?
3. What is the context's responsibility?
4. What does the context explicitly NOT own?
5. How does it communicate with other contexts?
6. What business invariants must it protect?

If these questions cannot be answered, stop and clarify the domain boundary before implementing.

## 2. Use Bounded Contexts

Use the term context, not "Django app", when discussing the architecture.
Each context represents a coherent business capability.
Examples may include:

* Identity / Users
* Tenancy
* Organizations
* Communities
* Contributions
* Ledger
* Payments
* Verification
* Controls
* Notifications
* Conversations
* Files
* Audit
* Backoffice

These are examples, not automatic boundaries.
A context should exist because it represents a meaningful business capability, not because a set of models happens to be related.

## 3. Every Context Has Clear Ownership

Every important domain concept must have an obvious owner.
There should be one authoritative context responsible for:

* its lifecycle
* its invariants
* its state transitions
* its persistence
* its domain rules

Other contexts may reference or consume that concept, but should not silently become secondary owners.
Avoid:

```text
User model duplicated across contexts
Payment logic inside Contributions
Contribution rules inside Payments
Ledger rules inside API views
Verification rules inside User serializers

```

Instead, establish explicit ownership.

## 4. No Cross-Context Database Coupling by Convenience

Do not reach into another context's internal models merely because Django makes it easy.
Avoid patterns such as:

```python
from contributions.models import Contribution

```

inside another context simply to manipulate its internal state.
Cross-context interaction should occur through an explicit contract.
Depending on the use case, that may be:

* application service
* domain command
* domain event
* query/read interface
* integration contract

A foreign key across contexts is not automatically forbidden, but it must be deliberate and documented.
The question is:
Does this relationship represent a legitimate domain relationship, or are we using the database to bypass a boundary?

## 5. Contexts Should Be Independently Understandable

A developer should be able to enter a context directory and understand:

* what the context does
* what it owns
* what its domain concepts are
* where business rules live
* how external requests enter
* how persistence works
* how it communicates with other contexts

Do not create a structure where understanding one context requires reading half the repository.

## 6. Standard Internal Context Structure

Prefer a consistent structure such as:

```text
<context>/
    api/
    application/
    domain/
    infrastructure/
    tests/

```

Where appropriate:

```text
<context>/
    api/
        urls.py
        views.py
        serializers.py

    application/
        commands/
        queries/
        services/

    domain/
        entities/
        value_objects/
        services/
        events/
        policies/
        exceptions.py

    infrastructure/
        models/
        repositories/
        providers/
        persistence/

    tests/
        unit/
        integration/
        api/

```

Do not create every directory mechanically.
The structure should reflect actual complexity.

## 7. Dependency Direction Matters

Prefer:

```text
API
 ↓
Application
 ↓
Domain
 ↑
Infrastructure

```

The domain must not depend on Django infrastructure.
Avoid:

```text
domain → Django ORM
domain → DRF
domain → Redis
domain → Celery
domain → M-Pesa

```

Instead:

```text
Domain
  ↓
interfaces / ports

Infrastructure
  ↓
implements those interfaces

```

Infrastructure is replaceable.
The domain is not.

## 8. Keep Django at the Edges

Django is the implementation framework, not the business model.
Use Django/DRF for things such as:

* HTTP
* authentication integration
* ORM
* transactions
* serialization
* routing
* middleware
* admin/backoffice infrastructure

Do not make Django models the only representation of business concepts.
If a business rule is important enough to matter independently of HTTP or the database, it should not live exclusively in:

```python
serializer.validate()
view()
model.save()
signal()

```

## 9. Rich Domain Model

Prefer explicit domain concepts over primitive data structures when business meaning exists.
For example:

```text
Money
Account
Contribution
ContributionGoal
Approval
Payment
JournalEntry
JournalLine
Tenant
Membership
Verification

```

should have meaningful behavior and invariants.
Avoid an anemic model where everything becomes:

```python
dict + service function + database update

```

Use domain behavior where it improves correctness.

## 10. Business Rules Must Have One Home

A business rule must have a clearly identifiable location.
Do not duplicate the same rule across:

* serializer
* view
* model
* service
* Celery task
* admin
* mobile client

For example, if a contribution cannot exceed a defined limit, there should be one authoritative rule.
Other layers may validate early for UX, but they must not become alternate authorities.

## 11. API Is an Adapter, Not the Domain

API code should primarily translate:

```text
HTTP request
    ↓
application command/query
    ↓
domain
    ↓
result
    ↓
HTTP response

```

Avoid putting substantial business logic into:

```python
APIView
ViewSet
Serializer
URL handler

```

A serializer should not become a hidden application service.

## 12. Application Layer Coordinates Use Cases

Application services should answer questions such as:

```text
Create community
Submit contribution
Approve contribution
Initiate payment
Complete verification
Post financial transaction
Generate report

```

They coordinate domain operations.
They should not become giant "god services" containing every business rule.
Bad:

```text
CommunityService
    2,000 lines
    creates users
    handles payments
    posts ledger entries
    sends notifications
    performs KYC

```

Prefer focused use cases.

## 13. Domain vs Application vs Infrastructure

Use this test:
Domain
"What is true about the business?"
Examples:

```text
A journal must balance.
A contribution belongs to a goal.
A frozen account cannot transact.
An approval cannot be approved twice.

```

Application
"What operation are we performing?"
Examples:

```text
CreateContribution
ApproveVerification
InitiatePayment
PostJournal

```

Infrastructure
"How does the system interact with the outside world?"
Examples:

```text
Postgres
Redis
M-Pesa
email provider
SMS provider
Celery
Django ORM

```

API
"How does an external client interact with the application?"

## 14. No Hidden Business Logic in Signals

Do not use Django signals as invisible business workflows.
Avoid:

```text
save User
 ↓
signal
 ↓
create account
 ↓
signal
 ↓
create contribution
 ↓
signal
 ↓
send notification

```

This makes workflows difficult to reason about, test, replay, and audit.
Use explicit application workflows.
Signals may be used for genuinely infrastructural concerns where appropriate, but never as the primary mechanism for important domain workflows.

## 15. Transactions Must Match Business Boundaries

Database transactions should protect business invariants.
If an operation must be atomic:

```text
validate
→ change state
→ persist
→ create required outbox event

```

should occur within the appropriate transaction boundary.
Do not scatter `transaction.atomic()` randomly.
Every significant transaction should have an understandable business reason.

## 16. Events Must Be Intentional

Use events when something meaningful has happened.
Examples:

```text
ContributionCreated
PaymentCompleted
VerificationApproved
JournalPosted
MembershipAccepted

```

Do not create events merely because a database row changed.
An event should communicate a business fact.
Events should not secretly become a second application architecture.

## 17. Prefer Explicit Workflows Over Magic

WEPL handles financial and governance workflows.
Predictability is more important than cleverness.
Prefer:

```python
approve_verification(...)

```

over hidden chains of:

```text
save()
 → signal
 → callback
 → task
 → another callback

```

A developer should be able to trace a critical workflow from entry point to final effect.

## 18. Financial Domain Has the Highest Integrity Requirements

Treat the ledger as a foundational context.
The ledger must not become a reporting convenience.
Financial state should be:

* explicit
* auditable
* immutable where appropriate
* reproducible
* balanced
* idempotent
* traceable

Never manipulate balances directly when the authoritative accounting mechanism should be used.
Prefer:

```text
business event
→ accounting decision
→ journal
→ journal lines
→ derived balance

```

rather than:

```text
balance += amount

```

## 19. Never Delete Financial History to Correct It

Where financial records represent historical facts, prefer:

```text
reversal
correction
adjustment
compensating entry

```

over destructive mutation.
The system should be capable of answering:
What happened?
and:
Why does the current balance look like this?

## 20. Idempotency Is a First-Class Requirement

Any operation that may be retried must be designed for idempotency.
Especially:

* payment callbacks
* financial posting
* webhook processing
* background jobs
* notifications
* external provider operations
* outbox processing

Assume:

```text
network failure
+
timeout
+
retry
+
duplicate request

```

can happen.
Design accordingly.

## 21. External Providers Must Be Behind Interfaces

Do not allow M-Pesa, email, SMS, storage providers, or other vendors to become the domain model.
Prefer:

```text
PaymentProvider
    ├── MpesaProvider
    ├── FakePaymentProvider
    └── FutureProvider

```

The domain should care about:

```text
payment initiated
payment confirmed
payment failed

```

not the provider's proprietary implementation details.

## 22. Avoid Provider-Specific Domain Language

Avoid allowing:

```text
mpesa_receipt
mpesa_status
mpesa_callback

```

to become fundamental concepts everywhere.
Provider-specific information belongs at the integration boundary.
If a provider-specific fact is genuinely useful, model it as provider metadata rather than contaminating the entire domain.

## 23. Tenancy Is a Security Boundary

Tenant isolation must never depend solely on developers remembering to filter queries.
Tenant context should be established explicitly and consistently.
Every tenant-scoped operation must have a clear answer to:

```text
Which tenant does this belong to?

```

Cross-tenant access must fail safely.
Do not allow convenience queries such as:

```python
Model.objects.all()

```

inside tenant-sensitive business code unless there is an explicit reason.

## 24. Authorization Is Not the Same as Authentication

Authentication answers:
Who are you?
Authorization answers:
What are you allowed to do?
Tenant membership answers:
In which organizational context?
Business permissions answer:
Under what conditions may you perform this action?
Keep these concepts distinct.

## 25. Security Rules Should Be Explicit

Important security controls must be visible and testable.
Examples:

```text
tenant isolation
permission checks
account restrictions
session invalidation
verification requirements
approval requirements
transaction authorization

```

Do not rely on obscure framework behavior for critical security guarantees.

## 26. Read and Write Concerns May Differ

Do not force every operation through the same abstraction.
A transactional command may need:

```text
domain + repository

```

while a complex reporting query may legitimately use:

```text
optimized query/read model

```

The requirement is not "everything must use repositories."
The requirement is:
Business ownership and integrity must remain clear.

## 27. Reporting Must Not Become the Source of Truth

Reports are projections of authoritative data.
Do not create a report-specific table and then treat it as authoritative financial state unless explicitly designed as such.
Prefer:

```text
authoritative domain state
        ↓
projection/query
        ↓
report

```

## 28. Backoffice Is a Product Surface

Backoffice is not simply "Django admin."
It is an operational system for:

* user management
* verification
* approvals
* risk/compliance
* audit
* financial operations
* reconciliation
* support
* governance

It should use the same application/domain rules as the public API.
Never create a backdoor implementation of business rules merely because an operation is performed by staff.

## 29. Tests Follow Business Boundaries

Organize tests around behavior and context.
Prioritize:

1. domain invariants
2. application use cases
3. context boundaries
4. security/tenancy
5. integration contracts
6. API behavior
7. infrastructure

Do not measure quality primarily by percentage coverage.
A 95% covered system can still have badly designed business boundaries.

## 30. Test Failure Paths Explicitly

For critical workflows test:

```text
success
duplicate request
retry
timeout
partial failure
invalid state
unauthorized actor
wrong tenant
provider failure
database failure
recovery

```

Especially for financial operations.

## 31. Architecture Must Be Observable

Important workflows should be traceable.
Prefer consistent:

```text
request ID
correlation ID
tenant ID
actor ID
operation ID
idempotency key

```

where appropriate.
Logs should answer:

```text
Who?
What?
When?
Which tenant?
Which operation?
What changed?
Why did it fail?

```

Do not log secrets or sensitive credentials.

## 32. Audit Is Different From Logging

Logs explain what the software did operationally.
Audit explains what happened from a governance/accountability perspective.
Do not substitute:

```text
application logs

```

for:

```text
audit history

```

Important business actions should produce deliberate audit records.

## 33. Avoid Premature Microservices

The rebuild should begin as a well-bounded modular monolith unless there is a demonstrated reason to separate a component.
Good boundaries first.
Physical deployment boundaries later.
The objective is:

```text
modular monolith
→ independently understandable contexts
→ explicit contracts
→ measurable workload boundaries
→ extract only where justified

```

Do not create distributed-system complexity merely to appear scalable.

## 34. Scaling Should Follow Workload

When considering another technology such as Elixir/Phoenix, ask:

1. What workload requires it?
2. What characteristic of Django prevents us from handling it?
3. What latency/throughput requirement exists?
4. What operational complexity does introducing it add?
5. Does the workload justify a separate runtime?

Technology should solve a demonstrated constraint.

## 35. Repository Structure Should Reflect Architecture

Prefer something conceptually like:

```text
wepl/
├── backend/
│   ├── config/
│   ├── contexts/
│   │   ├── identity/
│   │   ├── tenants/
│   │   ├── organizations/
│   │   ├── communities/
│   │   ├── contributions/
│   │   ├── payments/
│   │   ├── ledger/
│   │   ├── verification/
│   │   ├── controls/
│   │   ├── notifications/
│   │   ├── conversations/
│   │   ├── files/
│   │   ├── audit/
│   │   └── backoffice/
│   └── tests/
│
├── web/
├── mobile/
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── domain/
│   └── operations/
│
└── infrastructure/

```

This is a guideline, not a rigid requirement.
If a better structure emerges from the domain, document why.

## 36. Documentation Is Part of the Architecture

Important architectural decisions must be documented.
Use ADRs for decisions such as:

```text
Why this context boundary?
Why this tenancy model?
Why this ledger model?
Why this integration boundary?
Why this consistency model?
Why this technology?

```

Do not document obvious implementation details as architecture.
Document decisions and constraints.

## 37. Avoid "Utils" and "Helpers" as Architectural Dumping Grounds

Do not create:

```text
utils.py
helpers.py
common.py
misc.py

```

and gradually place unrelated business logic there.
If code has business meaning, place it in the appropriate context.
If it is genuinely generic infrastructure, make that explicit.

## 38. Naming Should Use Domain Language

Names should describe business concepts rather than implementation mechanisms.
Prefer:

```text
Contribution
Approval
Verification
Settlement
JournalEntry
Membership

```

over:

```text
DataObject
TransactionHelper
ProcessRecord
GenericService

```

Use the same terminology consistently across:

```text
code
database
API
documentation
UI
tests

```

## 39. Avoid Generic "Service Layer" Everything

Do not create:

```text
services.py

```

and place every operation in it.
A service should have a clear responsibility.
If something is:

* a domain rule → domain
* a use case → application
* persistence → infrastructure
* transport → API
* external integration → infrastructure/provider

Place it accordingly.

## 40. Prefer Small, Explicit Modules

A file should have a reason to exist.
Avoid:

```text
models.py — 3,000 lines
services.py — 4,000 lines
views.py — 5,000 lines
utils.py — 2,000 lines

```

Split by domain responsibility.

## 41. Do Not Abstract Before the Need Exists

Do not introduce abstractions simply because they look architecturally sophisticated.
An abstraction should solve a real problem such as:

* replaceability
* testing
* isolation
* multiple implementations
* domain boundary
* external integration
* complexity management

Prefer simple code until a meaningful abstraction is justified.

## 42. But Do Not Allow Shortcuts to Become Architecture

A shortcut is acceptable only if it is visible and deliberate.
If something violates an architectural principle temporarily:

1. document it
2. identify the reason
3. identify the consequence
4. identify what would cause it to be revisited

Never let a temporary shortcut become an invisible permanent dependency.

## 43. Every Context Must Have an Explicit Public Surface

A context should expose only what other contexts are allowed to depend upon.
Think:

```text
CONTEXT
├── public contract
└── internal implementation

```

Other contexts should not depend on internal implementation details.
This makes future extraction possible.

## 44. Prefer Commands for State Changes

For significant mutations, think in terms of:

```text
Command
→ validate
→ execute
→ domain state change
→ persistence
→ events

```

rather than arbitrary model mutations from everywhere.
This creates traceable business workflows.

## 45. Prefer Queries for Reads

Reads should be optimized for the information required by the caller.
Do not load an entire aggregate merely to display:

```text
name
status
balance

```

Use appropriate query/read mechanisms.
Do not confuse read optimization with permission to bypass domain rules on writes.

## 46. State Machines Should Be Explicit

If an entity has meaningful states, model its transitions explicitly.
For example:

```text
PENDING
   ↓
PROCESSING
   ↓
SUCCESS
   ↓
REVERSED

```

Do not allow arbitrary:

```python
status = "SUCCESS"

```

from unrelated code.
Invalid transitions should fail.

## 47. Critical Invariants Must Be Enforced at Multiple Appropriate Layers

For example:

```text
application validation
+
domain validation
+
database constraint where practical

```

Do not assume application code alone can protect an invariant that the database can enforce.
But do not attempt to push all business rules into database constraints either.
Use each layer for what it is good at.

## 48. Concurrency Must Be Considered Explicitly

For shared state, ask:

```text
What happens if two requests arrive simultaneously?

```

Consider:

* row locking
* optimistic concurrency
* unique constraints
* idempotency
* transaction isolation
* atomic updates

Especially for:

```text
balances
approvals
membership
limits
payment state
inventory-like resources

```

## 49. Background Work Must Be Safe to Retry

Celery tasks should assume they can execute:

```text
zero times
one time
multiple times

```

The task must therefore be:

* idempotent where possible
* observable
* recoverable
* bounded
* explicit about failure

Do not rely on "Celery probably only runs it once."

## 50. Do Not Couple User Experience to Internal Architecture

The domain model should not be distorted merely to make a UI screen easier.
Likewise, do not create backend concepts solely because a frontend framework prefers them.
The UI consumes the domain.
It does not define it.

## 51. API Contracts Must Be Deliberate

API responses should represent stable external contracts.
Do not expose ORM models directly.
Avoid allowing internal database changes to accidentally become API changes.
Version or evolve contracts deliberately.

## 52. Database Schema Is Not the Domain Model

A table is persistence.
A domain entity is business meaning.
They may map closely, but they are not conceptually identical.
Do not allow:

```text
one table = one domain concept

```

to become an unquestioned architectural rule.

## 53. Performance Optimizations Must Preserve Domain Integrity

Before optimizing, identify:

```text
what is slow?
why is it slow?
what workload causes it?
what constraint must remain true?

```

Then optimize.
Do not sacrifice:

* auditability
* correctness
* tenant isolation
* idempotency
* financial integrity

for premature performance.

## 54. Security and Financial Integrity Override Convenience

When choosing between:

```text
easy implementation

```

and:

```text
stronger integrity

```

for a financial or security-critical workflow, design for integrity.
Convenience must not determine architecture.

## 55. Do Not Rebuild the Old System Blindly

The existing WEPL codebase is a source of:

* evidence
* lessons
* useful domain discoveries
* failed approaches
* existing constraints

It is not automatically the architecture for the rebuild.
For every inherited concept ask:

```text
Is this still required?
Is the boundary correct?
Is the name correct?
Is the responsibility correct?
Is the implementation still justified?

```

Reuse proven ideas.
Do not reproduce historical mistakes.

## 56. Do Not Invent Requirements

When the codebase or documentation does not establish a requirement, do not silently invent one.
Mark it as:

```text
Known
Inferred
Assumption
Open question

```

When an architectural decision depends on an unresolved business question, surface it rather than hiding the assumption in code.

## 57. Evidence-Driven Engineering

When analyzing the existing system or deciding whether to preserve a concept, classify conclusions as:

```text
CONFIRMED
    Directly supported by code/tests/docs.

STRONGLY INFERRED
    Multiple pieces of evidence support the conclusion.

INFERRED
    Reasonable interpretation but not explicitly established.

ASSUMPTION
    Required to proceed but not yet validated.

UNKNOWN
    Evidence is insufficient.

```

Do not present assumptions as facts.

## 58. Use ADRs for Architectural Disagreements

If there are multiple reasonable approaches, do not silently choose one for convenience.
Record:

```text
Context
Decision
Alternatives considered
Why chosen
Consequences

```

The objective is not bureaucracy.
The objective is preserving architectural reasoning.

## 59. Refactoring Must Preserve Behavior Unless Behavior Is Intentionally Changed

When moving existing functionality:

```text
understand behavior
→ identify intended behavior
→ write/verify tests
→ move/refactor
→ compare behavior

```

Do not assume that a cleaner implementation is automatically behaviorally equivalent.

## 60. The Golden Rule

Before adding code, ask:
What business concept am I implementing, which context owns it, what invariant does it protect, and what contract does it expose?
If those questions have clear answers, implement.
If they do not, investigate the domain first.
The goal of this rebuild is not merely to produce cleaner Django code.
The goal is to produce a system whose architecture reflects the business, whose contexts have clear ownership, whose financial state is trustworthy, and whose boundaries allow WEPL to scale without turning the codebase into another monolith.
