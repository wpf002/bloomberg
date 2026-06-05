"""The GitHub OAuth callback URL must be https for the public host — Railway
terminates TLS at its proxy so the app sees http internally, which GitHub
rejects ("redirect_uri is not associated with this application")."""

from backend.api.routes.auth import _public_https


def test_railway_http_is_upgraded_to_https():
    raw = "http://backend-production-4975.up.railway.app/api/auth/github/callback"
    out = _public_https(raw, forwarded_proto=None)
    assert out == "https://backend-production-4975.up.railway.app/api/auth/github/callback"


def test_forwarded_proto_https_is_honored():
    raw = "http://backend-production-4975.up.railway.app/api/auth/github/callback"
    out = _public_https(raw, forwarded_proto="https")
    assert out.startswith("https://")


def test_forwarded_proto_list_takes_first():
    raw = "http://example.up.railway.app/api/auth/github/callback"
    out = _public_https(raw, forwarded_proto="https, http")
    assert out.startswith("https://")


def test_localhost_stays_http_for_dev():
    raw = "http://localhost:8000/api/auth/github/callback"
    out = _public_https(raw, forwarded_proto=None)
    assert out == raw  # local dev must not be force-upgraded


def test_already_https_is_unchanged():
    raw = "https://backend-production-4975.up.railway.app/api/auth/github/callback"
    assert _public_https(raw, forwarded_proto=None) == raw
