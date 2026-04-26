"""Pytest coverage for backend/core/audit.py and the Module-5 schema.

Network-free: we don't need a live Postgres because every audit helper
no-ops gracefully when database.pool is None. We test that contract
plus the schema's import surface.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core import audit, schema
from backend.core.database import database


def test_schema_includes_all_module5_hypertables():
    ddl = schema.HYPERTABLE_DDL
    for table in (
        "market_data",
        "macro_series",
        "normalized_records",
        "audit_log",
        "risk_snapshots",
        "intelligence_snapshots",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl


def test_hypertable_policies_register_create_hypertable_for_each_table():
    pol = schema.HYPERTABLE_POLICIES
    for table in (
        "market_data",
        "macro_series",
        "normalized_records",
        "audit_log",
        "risk_snapshots",
        "intelligence_snapshots",
    ):
        assert f"create_hypertable('{table}'" in pol
    # Compression policy bookkeeping
    assert "compress_segmentby = 'symbol'" in pol
    assert "add_compression_policy('audit_log'" in pol


def test_hash_inputs_is_stable_and_short():
    a = audit._hash_inputs({"x": 1, "y": [1, 2, 3]})
    b = audit._hash_inputs({"y": [1, 2, 3], "x": 1})  # key order reversed
    assert a == b
    assert len(a) == 12


def test_audit_helpers_no_op_when_pool_is_none():
    # Defensive contract: all five helpers must complete without raising
    # when the Postgres pool isn't connected.
    assert database.pool is None
    asyncio.get_event_loop().run_until_complete(
        audit.persist_audit(record_id="x", source="t", symbol="AAPL")
    )

    class _Rec:
        ingested_at = None
        timestamp = None
        source = "t"
        symbol = "AAPL"
        series_id = "price"
        value = 1.0
        unit = "USD"
        tags = {}

    asyncio.get_event_loop().run_until_complete(audit.persist_normalized(_Rec()))
    asyncio.get_event_loop().run_until_complete(
        audit.persist_intelligence_snapshot("regime", {"x": 1}, {"y": 2})
    )
    asyncio.get_event_loop().run_until_complete(
        audit.persist_risk_snapshot("var", {"y": 2})
    )

    rows = asyncio.get_event_loop().run_until_complete(audit.fetch_audit("AAPL"))
    assert rows == []
    snaps = asyncio.get_event_loop().run_until_complete(
        audit.fetch_intelligence_snapshots("regime")
    )
    assert snaps == []


def test_audit_route_handles_missing_postgres():
    from backend.api.routes import audit as audit_route

    payload = asyncio.get_event_loop().run_until_complete(
        audit_route.get_audit(symbol="AAPL")
    )
    assert payload["rows"] == []
    assert payload["note"] is not None
