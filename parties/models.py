import re

from django.core.exceptions import ValidationError
from django.db import models


def normalize_msisdn(value: str) -> str:
    """Return a Kenyan mobile number as 2547XXXXXXXX / 2541XXXXXXXX."""
    digits = re.sub(r"\D", "", value or "")
    match = re.fullmatch(r"(?:254|0)?([17]\d{8})", digits)
    if not match:
        raise ValidationError(f"{value!r} is not a Kenyan mobile number.")
    return "254" + match.group(1)


class Person(models.Model):
    """A human, identified by a mobile number. Identity documents are held by
    the custodian bank (I&M), not by WEPL."""

    msisdn = models.CharField(max_length=12, unique=True)
    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.msisdn = normalize_msisdn(self.msisdn)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.display_name} ({self.msisdn})"
