from django.db import IntegrityError, transaction

from ..contract import PersonView
from ..domain.msisdn import Msisdn
from ..infrastructure.models import Person


def register_person(msisdn: str, name: str) -> PersonView:
    """Find the person with this number, or register them. Safe to repeat."""
    number = Msisdn.parse(msisdn).value
    person = Person.objects.filter(msisdn=number).first()
    if person is None:
        try:
            with transaction.atomic():  # the unique number decides a race
                person = Person.objects.create(msisdn=number, display_name=name.strip()[:120])
        except IntegrityError:
            person = Person.objects.get(msisdn=number)
    return _view(person)


def people(ids) -> dict[int, PersonView]:
    return {p.pk: _view(p) for p in Person.objects.filter(pk__in=list(ids))}


def _view(p: Person) -> PersonView:
    return PersonView(id=p.pk, msisdn=p.msisdn, name=p.display_name)
