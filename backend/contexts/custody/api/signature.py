"""Is a request from the bank? An HMAC-SHA256 signature over the timestamp
and the body, with a shared secret (ADR-0019).

ASSUMPTION: the bank can sign requests. The mechanism (signature, mutual TLS
or an IP allowlist) is to be agreed at the sit-down with its developers; this
is the placeholder until then. A replay inside the window is harmless: the
reference check is read-only and a notification is idempotent by the bank's
transaction id."""
import hashlib
import hmac

WINDOW_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def refusal(secret: str, *, timestamp: str, signature: str, body: bytes, now: float) -> str | None:
    """Why the request is refused, or None if it is genuine and fresh."""
    if not timestamp.isdigit() or abs(now - int(timestamp)) > WINDOW_SECONDS:
        return "stale or missing timestamp"
    if not hmac.compare_digest(sign(secret, timestamp, body), signature or ""):
        return "bad signature"
    return None
