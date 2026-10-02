"""What of a message may appear in logs. Phone numbers and names are personal
data (Kenya Data Protection Act), so logs keep only enough to trace a message."""
PHONE_KEYS = frozenset({"msisdn"})
NAME_KEYS = frozenset({"payer", "payee", "counterparty", "name"})


def mask_phone(value) -> str:
    digits = str(value or "")
    return f"***{digits[-3:]}" if len(digits) > 3 else "***"


def for_log(payload: dict) -> dict:
    return {k: mask_phone(v) if k in PHONE_KEYS else "[redacted]" if k in NAME_KEYS else v
            for k, v in payload.items()}
