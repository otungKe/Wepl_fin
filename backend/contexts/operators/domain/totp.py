"""Time-based one-time codes (RFC 6238: HMAC-SHA1, 30 seconds, 6 digits),
the codes authenticator apps show. Pure: the caller supplies the time."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

STEP = 30
DIGITS = 6
DRIFT = 1  # steps either side accepted, for a phone clock a little off


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def step_of(timestamp: float) -> int:
    return int(timestamp // STEP)


def matching_step(secret: str, code: str, *, now: float, last_used: int | None) -> int | None:
    """The step the code belongs to, or None. A code is used once: a step at
    or before the last one accepted is refused, so a code seen over someone's
    shoulder cannot be replayed."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = step_of(now)
    for step in range(current - DRIFT, current + DRIFT + 1):
        if (last_used is None or step > last_used) and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, *, account: str, issuer: str = "WEPL") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")
