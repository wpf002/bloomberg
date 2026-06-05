"""Symmetric encryption for secrets at rest (per-user broker credentials).

Uses Fernet (AES-128-CBC + HMAC). The key is taken from `BROKER_ENC_KEY`
when set; otherwise it's deterministically derived from the app signing
secret (`SECRET_KEY`/`JWT_SECRET`) so production — which already sets
SECRET_KEY for JWTs — gets stable encryption without a second secret.

Caveat (documented intentionally): rotating the underlying secret
invalidates previously-stored ciphertext. For broker keys that just means
the user re-enters them in Settings.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

logger = logging.getLogger(__name__)


class EncryptionUnavailable(RuntimeError):
    """Raised when no key material is available to encrypt/decrypt."""


def _fernet() -> Fernet:
    raw = settings.broker_enc_key or settings.signing_secret
    if not raw:
        # No configured secret at all (pure dev with nothing set). We refuse
        # rather than silently store plaintext-equivalent data.
        raise EncryptionUnavailable(
            "No BROKER_ENC_KEY or SECRET_KEY/JWT_SECRET configured — cannot "
            "encrypt broker credentials. Set SECRET_KEY in the environment."
        )
    # If the operator handed us a valid 32-byte urlsafe Fernet key, use it
    # directly; otherwise derive one deterministically via SHA-256.
    try:
        candidate = raw.encode() if isinstance(raw, str) else raw
        Fernet(candidate)  # validates length/format
        return Fernet(candidate)
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string → urlsafe ciphertext token."""
    if plaintext is None:
        raise ValueError("cannot encrypt None")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a token produced by `encrypt`. Raises on tamper/wrong key."""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("could not decrypt (wrong key or corrupt data)") from exc


def encryption_available() -> bool:
    try:
        _fernet()
        return True
    except Exception:
        return False
