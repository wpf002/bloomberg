"""Encryption helper — roundtrip + tamper/wrong-key failure."""

import pytest

from backend.core import encryption
from backend.core.config import settings


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "broker_enc_key", None, raising=False)
    monkeypatch.setattr(settings, "secret_key", "unit-test-secret-key", raising=False)
    yield


def test_roundtrip():
    token = encryption.encrypt("PKABC123SECRET")
    assert token != "PKABC123SECRET"  # actually encrypted
    assert encryption.decrypt(token) == "PKABC123SECRET"


def test_available():
    assert encryption.encryption_available() is True


def test_wrong_key_fails(monkeypatch):
    token = encryption.encrypt("hello")
    # rotate the secret → old ciphertext no longer decrypts
    monkeypatch.setattr(settings, "secret_key", "a-totally-different-secret", raising=False)
    with pytest.raises(ValueError):
        encryption.decrypt(token)


def test_unavailable_without_secret(monkeypatch):
    monkeypatch.setattr(settings, "broker_enc_key", None, raising=False)
    monkeypatch.setattr(settings, "secret_key", None, raising=False)
    monkeypatch.setattr(settings, "jwt_secret", None, raising=False)
    assert encryption.encryption_available() is False
    with pytest.raises(encryption.EncryptionUnavailable):
        encryption.encrypt("x")
