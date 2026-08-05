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
