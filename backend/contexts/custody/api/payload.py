"""WEPL's placeholder request format for the bank's collections service,
until the real one is agreed (ADR-0018). A bank adapter will map the bank's
own format onto these same fields; nothing past this module sees either."""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from ..domain.statement import BankLine, LineKind


class BadPayload(ValueError):
    pass


def bank_line(data: dict) -> BankLine:
    """A payment notification as a statement line. Every field the
    reconciliation relies on is required; anything missing is refused, so the
    bank resends rather than WEPL guessing."""
    try:
        posted_at = datetime.fromisoformat(data["posted_at"])
        balance = data.get("running_balance")
        line = BankLine(
            external_id=str(data["transaction_id"]), sequence=int(data["sequence"]), posted_at=posted_at,
            kind=LineKind(data["kind"]), amount=Decimal(str(data["amount"])),
            narration=str(data.get("narration", "")), reference=str(data.get("reference", "")),
            counterparty_name=str(data.get("payer_name", "")), counterparty_msisdn=str(data.get("payer_msisdn", "")),
            running_balance=Decimal(str(balance)) if balance is not None else None,
            metadata={"source": "collections_api", "channel": str(data.get("channel", ""))})
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise BadPayload(f"Not a payment notification: {exc!r}") from None
    if not line.external_id or line.amount <= 0 or posted_at.tzinfo is None:
        raise BadPayload("A notification needs a transaction id, a positive amount and a dated time zone.")
    return line
