"""Send the daily digest to WEPL's operations address.

Sent every night, even when nothing is open: an operator who gets no email
knows the jobs did not run. Email is not a private channel, so the digest
holds counts only (``domain.digest``)."""
import logging

from django.conf import settings
from django.core.mail import send_mail

from ..domain.digest import StepOutcome, body, subject
from ..domain.inbox import InboxItem

log = logging.getLogger("wepl.operations")


def send_digest(steps: list[StepOutcome], items: list[InboxItem]) -> str:
    """Returns the digest text. Without an operations address it is only
    logged, which is how development and tests run."""
    text = body(steps, items)
    to = settings.WEPL_OPERATIONS_EMAIL
    if to:
        send_mail(subject(steps, items), text, settings.DEFAULT_FROM_EMAIL, [to])
    else:
        log.info("digest not emailed (WEPL_OPERATIONS_EMAIL unset): %s", subject(steps, items))
    return text
