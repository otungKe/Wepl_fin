"""Identity context.

Owns: people and their phone numbers (a person's identity across all groups).

Does not own: what a person may do in a group (communities and governance),
or authentication, which comes later (phone number plus one-time code).

A person's mobile number is, until member login exists, all of these at once:
the key that finds them (one person per number, enforced by the database), the
number messages go to, and the number payments and payouts are matched on
(custody, and governance's no-self-benefit rule). Their name is the one every
group they join shows. Registering never changes an existing person; a
wrong name or number is fixed by ``correct_person``, a declared cross-tenant
operation, audited with its reason. A recycled number is handled the same way:
move the old owner off it before the new owner registers.

Public surface: ``contexts.identity.public``.
"""
