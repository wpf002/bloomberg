"""Structured JSON logging + a request-timing middleware.

Two pieces:

1. `configure_logging()` swaps the root handler to one that emits a
   single-line JSON object per record. Anthropic / Railway / Datadog /
   most cloud log aggregators happily index JSON-formatted stdout.

2. `RequestLoggingMiddleware` logs one line per HTTP request with method,
   path, status code, and duration in milliseconds. Health-check spam
   (`/healthz` every few seconds from Railway's probe) is dropped at the
   handler level so it doesn't drown out real traffic.

Helpers:

- `log_upstream(...)` — every call to an external API (Alpaca, FRED, …)
  should call this so we can grep for slow upstream calls.
- `log_advisor(...)` — Claude calls log capability + token counts. We
  deliberately do NOT log prompt content (PII / strategy leakage).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


# ── secret redaction ────────────────────────────────────────────────────────

# Several upstreams (FMP, FRED, Finnhub) authenticate with the key in the
# query string rather than a header, and httpx logs the full request URL at
# INFO — so without this the keys land in Railway's log stream verbatim on
# every call. Redact at the formatter so it covers third-party loggers we
# don't control, not just our own log_* helpers.
_SECRET_QS = re.compile(
    r"(?i)\b(apikey|api_key|access_token|auth_token|token|key|secret|password|signature)"
    r"=([^&\s\"'<>]+)"
)

# Postgres/Redis credentials ride in the URL's userinfo section rather than a
# query param, and driver connection errors routinely embed the whole DSN —
# so `_SECRET_QS` alone leaves the database password exposed. Matches both
# `scheme://user:pw@host` and Redis' password-only `scheme://:pw@host`.
_SECRET_DSN = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]*)(:)([^/\s@]+)(@)")


def _keep_prefix(value: str) -> str:
    """First 3 chars when the value is long enough that a prefix doesn't
    meaningfully narrow it down; otherwise nothing."""
    return value[:3] if len(value) > 8 else ""


def redact(text: str) -> str:
    """Mask credentials in query params and URL userinfo, keeping enough to
    identify which credential was used when debugging."""
    def _mask_qs(m: re.Match[str]) -> str:
        name, value = m.group(1), m.group(2)
        return f"{name}={_keep_prefix(value)}...[REDACTED]"

    def _mask_dsn(m: re.Match[str]) -> str:
        scheme, user, colon, _pw, at = m.groups()
        # Keep the username — it's useful context and not a secret.
        return f"{scheme}{user}{colon}...[REDACTED]{at}"

    return _SECRET_DSN.sub(_mask_dsn, _SECRET_QS.sub(_mask_qs, text))


# ── JSON formatter ──────────────────────────────────────────────────────────


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON line.

    Standard fields: ts, level, name, msg. Anything attached via the
    `extra=...` kwarg (which becomes attributes on the record) is folded
    into the same object so the structured fields ride along with the
    free-text message.
    """

    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "name": record.name,
            "msg": redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = redact(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                payload[key] = redact(repr(value))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Replace any pre-existing handlers with a single JSON-emitting one.

    Called once at import time from main.py — calling twice is harmless
    because we tear down existing handlers first.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Uvicorn brings its own access log that fights with ours. Silence
    # its access logger; we emit our own structured access lines via
    # RequestLoggingMiddleware.
    logging.getLogger("uvicorn.access").disabled = True


# ── per-request access log ─────────────────────────────────────────────────


_access_logger = logging.getLogger("http.access")
_HEALTH_PATHS = {"/healthz", "/", "/favicon.ico"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            _access_logger.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        if request.url.path not in _HEALTH_PATHS:
            _access_logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status,
                    "duration_ms": round(duration_ms, 2),
                },
            )
        return response


# ── helpers for upstream / advisor calls ───────────────────────────────────


_upstream_logger = logging.getLogger("upstream")
_advisor_logger = logging.getLogger("advisor")


def log_upstream(
    *,
    source: str,
    symbol: str | None,
    duration_ms: float,
    cached: bool = False,
    status: str = "ok",
) -> None:
    """One-line structured log for any external HTTP call.

    `source` is the data-source label ("alpaca", "fred", "finnhub", …).
    `cached=True` means the response was served from Redis without
    actually hitting the upstream.
    """
    _upstream_logger.info(
        "upstream",
        extra={
            "source": source,
            "symbol": symbol,
            "duration_ms": round(duration_ms, 2),
            "cached": cached,
            "status": status,
        },
    )


def log_advisor(
    *,
    capability: str,
    model: str,
    tokens_used: int | None,
    duration_ms: float,
    status: str = "ok",
) -> None:
    """One-line structured log for an AI advisor call.

    Deliberately omits prompt text — both for size reasons and because
    the prompt contains user portfolio / thesis data that we don't want
    sitting in log archives.
    """
    _advisor_logger.info(
        "advisor",
        extra={
            "capability": capability,
            "model": model,
            "tokens_used": tokens_used,
            "duration_ms": round(duration_ms, 2),
            "status": status,
        },
    )
