"""Credential redaction in the log formatter.

Several upstreams authenticate via query string (FMP's `apikey`, FRED,
Finnhub) and httpx logs the full request URL at INFO, so without redaction
those keys land in the production log stream on every call.
"""

from __future__ import annotations

import json
import logging

from backend.core.observability import JsonFormatter, redact


# ── redact() ───────────────────────────────────────────────────────────────

def test_redacts_fmp_apikey():
    url = "https://financialmodelingprep.com/stable/quote?symbol=CLUSD&apikey=abc123def456ghi"
    out = redact(url)
    assert "abc123def456ghi" not in out
    assert "[REDACTED]" in out
    assert "symbol=CLUSD" in out  # non-secret params survive


def test_keeps_prefix_for_debuggability():
    # Enough to tell *which* key was used, not enough to use it.
    out = redact("?apikey=abc123def456ghi")
    assert out == "?apikey=abc...[REDACTED]"


def test_short_values_fully_masked():
    # Too short to leak a prefix from safely.
    assert redact("?token=shortie") == "?token=...[REDACTED]"


def test_redacts_each_flagged_param():
    for name in ("apikey", "api_key", "access_token", "token", "secret", "password"):
        out = redact(f"https://x.test/a?{name}=SUPERSECRETVALUE")
        assert "SUPERSECRETVALUE" not in out, name


def test_case_insensitive():
    assert "SECRETVAL" not in redact("?ApiKey=SECRETVALUE123")


def test_redacts_multiple_params_in_one_url():
    out = redact("https://x.test/a?apikey=AAAAAAAAAA&sym=SPY&token=BBBBBBBBBB")
    assert "AAAAAAAAAA" not in out and "BBBBBBBBBB" not in out
    assert "sym=SPY" in out


def test_leaves_clean_urls_untouched():
    url = "https://paper-api.alpaca.markets/v2/positions"
    assert redact(url) == url


def test_does_not_eat_following_params():
    # The value match must stop at & so later params stay readable.
    assert "symbol=SPY" in redact("?apikey=AAAAAAAAAA&symbol=SPY")


# ── DSN userinfo ───────────────────────────────────────────────────────────
# Postgres/Redis creds live in the URL userinfo, not a query param, and driver
# connection errors embed the full DSN.

def test_redacts_postgres_password():
    out = redact("could not connect: postgresql://appuser:Sup3rSecret!@db.internal:5432/railway")
    assert "Sup3rSecret!" not in out
    assert "appuser" in out          # username is useful context, not a secret
    assert "db.internal:5432" in out  # host survives for debugging


def test_redacts_redis_password_only_form():
    # Redis DSNs commonly omit the user: redis://:password@host
    out = redact("redis://:H1ddenRedisPw@redis.internal:6379/0")
    assert "H1ddenRedisPw" not in out
    assert "redis.internal:6379" in out


def test_redacts_any_scheme():
    for scheme in ("postgresql", "postgres", "redis", "rediss", "amqp", "mongodb"):
        out = redact(f"{scheme}://u:TOPSECRETVALUE@h/db")
        assert "TOPSECRETVALUE" not in out, scheme


def test_leaves_credential_free_urls_intact():
    for url in (
        "https://paper-api.alpaca.markets/v2/positions",
        "https://docs.example.com/guide",
        "postgresql://db.internal:5432/railway",  # no userinfo at all
    ):
        assert redact(url) == url


def test_formatter_redacts_dsn_in_exception_text():
    try:
        raise ConnectionError("connect to postgresql://u:LiveDbPassword@h:5432/db failed")
    except ConnectionError:
        import sys
        rec = logging.LogRecord(
            name="database", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="db connect failed", args=(), exc_info=sys.exc_info(),
        )
        line = JsonFormatter().format(rec)
    assert "LiveDbPassword" not in line


# ── formatter integration ──────────────────────────────────────────────────

def _record(msg: str, **extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_formatter_redacts_message():
    line = JsonFormatter().format(
        _record('HTTP Request: GET https://fmp.test/q?apikey=LIVEKEY1234567 "200 OK"')
    )
    assert "LIVEKEY1234567" not in line
    assert json.loads(line)["level"] == "info"


def test_formatter_redacts_extra_string_fields():
    line = JsonFormatter().format(_record("upstream", url="https://x.test?apikey=LIVEKEY1234567"))
    assert "LIVEKEY1234567" not in line


def test_formatter_preserves_non_string_extras():
    payload = json.loads(JsonFormatter().format(_record("upstream", duration_ms=42, ok=True)))
    assert payload["duration_ms"] == 42 and payload["ok"] is True


def test_formatter_output_is_valid_json():
    payload = json.loads(JsonFormatter().format(_record("plain message")))
    assert payload["msg"] == "plain message"
    assert payload["name"] == "httpx"


# ── logging must not block the event loop ─────────────────────────────────

class _SlowStream:
    """A stderr whose consumer has fallen behind: every write takes 200ms."""

    def __init__(self):
        self.lines = []

    def write(self, s):
        import time
        time.sleep(0.2)
        self.lines.append(s)

    def flush(self):
        pass


def test_log_calls_do_not_wait_on_a_slow_consumer(monkeypatch):
    """Railway's log forwarder fell 27s behind in production; with a stream
    handler on the event loop, every log call then blocked the process."""
    import sys
    import time
    from backend.core import observability

    slow = _SlowStream()
    monkeypatch.setattr(sys, "stderr", slow)
    observability.configure_logging("INFO")
    try:
        log = logging.getLogger("backend.test.slow")
        t0 = time.perf_counter()
        for i in range(5):
            log.warning("line %d", i)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1, f"5 log calls took {elapsed:.2f}s; the caller is blocking on the write"
    finally:
        observability._stop_listener()
    assert len(slow.lines) == 5, "queued records should still be written"


def test_root_logs_through_a_queue():
    from logging.handlers import QueueHandler
    from backend.core import observability

    observability.configure_logging("INFO")
    try:
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1 and isinstance(handlers[0], QueueHandler)
    finally:
        observability._stop_listener()


def test_httpx_request_lines_quiet_outside_debug():
    from backend.core import observability

    observability.configure_logging("INFO")
    try:
        assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
    finally:
        observability._stop_listener()
