from django.db import IntegrityError, transaction

from contexts.audit.public import record
from contexts.tenancy.public import require_cross_tenant

from ..contract import PersonView
from ..domain.msisdn import Msisdn
from ..domain.person import IdentityError, clean_name
from ..infrastructure.models import Person


def register_person(msisdn: str, name: str) -> PersonView:
    """Find the person with this number, or register them. Safe to repeat.
    An existing person keeps their name: one group cannot rename a person
    every other group also sees (correct_person does that)."""
    number = Msisdn.parse(msisdn).value
    name = clean_name(name)
    person = Person.objects.filter(msisdn=number).first()
    if person is None:
        try:
            with transaction.atomic():  # the unique number decides a race
                person = Person.objects.create(msisdn=number, display_name=name)
        except IntegrityError:
            person = Person.objects.get(msisdn=number)
    return _view(person)


@transaction.atomic
def correct_person(person_id: int, *, name: str | None = None, msisdn: str | None = None, reason: str,
                   actor: str) -> PersonView:
    """Correct a person's name or number: a typo at onboarding, or a number
    they no longer hold (a recycled number goes to its new owner only after
    the old owner's record is moved off it). Every group the person belongs to
    sees the change, so it runs only in a declared cross-tenant operation and
    is audited with its reason. A number registered to someone else is
    refused: two records are never merged by a correction."""
    require_cross_tenant()
    if not (reason or "").strip():
        raise IdentityError("A correction must say why.")
    person = Person.objects.select_for_update().filter(pk=person_id).first()
    if person is None:
        raise IdentityError(f"Unknown person {person_id}.")
    changes = {}
    if name is not None and (new_name := clean_name(name)) != person.display_name:
        changes["name"] = {"from": person.display_name, "to": new_name}
        person.display_name = new_name
    if msisdn is not None and (number := Msisdn.parse(msisdn).value) != person.msisdn:
        changes["msisdn"] = {"from": person.msisdn, "to": number}
        person.msisdn = number
    if not changes:
        return _view(person)
    try:
        with transaction.atomic():
            person.save(update_fields=["display_name", "msisdn"])
    except IntegrityError:
        raise IdentityError(f"{person.msisdn} already belongs to another person.") from None
    record(actor, "person.corrected", target_type="person", target_id=person.pk,
           data={"reason": reason.strip(), **changes})
    return _view(person)


def people(ids) -> dict[int, PersonView]:
    """The people with these ids. An id with no person is absent, not an error."""
    return {p.pk: _view(p) for p in Person.objects.filter(pk__in=list(ids))}


def _view(p: Person) -> PersonView:
    return PersonView(id=p.pk, msisdn=p.msisdn, name=p.display_name)
