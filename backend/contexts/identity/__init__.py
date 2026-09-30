"""Identity context.

Owns: people and their phone numbers (a person's identity across all groups).

Does not own: what a person may do in a group (communities and governance),
or authentication, which comes later (phone number plus one-time code).

Public surface: ``contexts.identity.public``.
"""
