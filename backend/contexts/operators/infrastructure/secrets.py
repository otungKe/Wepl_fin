"""Authenticator secrets are encrypted at rest with WEPL_OPERATOR_KEY
(ADR-0021), so a copy of the database alone cannot produce codes."""
import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _fernet() -> Fernet:
    key = settings.WEPL_OPERATOR_KEY
    if not key:  # development only: settings refuse to boot without it when DEBUG is off
        key = base64.urlsafe_b64encode(hashlib.sha256(f"wepl-operator:{settings.SECRET_KEY}".encode()).digest())
    return Fernet(key)


def seal(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def unseal(token) -> str:
    return _fernet().decrypt(bytes(token)).decode()
