"""Auth on the sessionless bot monitor endpoint.

The token moved from a `?token=` query param to an Authorization header:
query strings end up in proxy and access logs, so the old form leaked the
secret on every call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.routes import bots as bots_routes
from backend.main import app

TOKEN = "test-monitor-token-0123456789"
URL = "/api/bots/monitor"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(bots_routes.settings, "bots_monitor_token", TOKEN)

    async def no_bots():
        return []

    async def no_health(ids):
        return {}

    # The auth gate is what's under test; keep the bot store out of it.
    monkeypatch.setattr(bots_routes.store, "list_active_bots", no_bots)
    monkeypatch.setattr(bots_routes.health_mod, "read_many", no_health)
    return TestClient(app)


def test_bearer_token_accepted(client):
    r = client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["active_count"] == 0


def test_bearer_scheme_is_case_insensitive(client):
    r = client.get(URL, headers={"Authorization": f"bearer {TOKEN}"})
    assert r.status_code == 200


def test_wrong_token_rejected(client):
    r = client.get(URL, headers={"Authorization": "Bearer not-the-token"})
    assert r.status_code == 401


def test_prefix_of_token_rejected(client):
    r = client.get(URL, headers={"Authorization": f"Bearer {TOKEN[:-1]}"})
    assert r.status_code == 401


def test_missing_header_rejected(client):
    assert client.get(URL).status_code == 401


def test_non_bearer_scheme_rejected(client):
    r = client.get(URL, headers={"Authorization": f"Basic {TOKEN}"})
    assert r.status_code == 401


def test_query_param_refused_even_with_correct_token(client):
    """A caller still on the old form must fail loudly, not be served."""
    r = client.get(URL, params={"token": TOKEN})
    assert r.status_code == 400
    assert "Authorization: Bearer" in r.json()["detail"]


def test_query_param_refused_alongside_valid_header(client):
    # Refuse rather than ignore: the secret is already in the URL, so the
    # caller needs to learn to stop sending it.
    r = client.get(
        URL,
        params={"token": TOKEN},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert r.status_code == 400


def test_unconfigured_server_returns_503(client, monkeypatch):
    monkeypatch.setattr(bots_routes.settings, "bots_monitor_token", None)
    r = client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 503
