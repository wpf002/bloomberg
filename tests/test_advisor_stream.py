"""The advisor streaming adapter must survive a mid-stream error and surface
it as readable text instead of aborting the connection (which the browser
shows as an opaque 'network error').

These tests manage their own event loop and restore a fresh one afterward so
they don't disturb sibling tests that rely on the implicit main-thread loop.
"""

import asyncio

from backend.api.routes.advisor import _stream_response


async def _failing_gen():
    yield "partial answer "
    raise RuntimeError("boom upstream")


async def _clean_gen():
    yield "hello "
    yield "world"


async def _agg(resp) -> str:
    chunks = []
    async for c in resp.body_iterator:
        chunks.append(c if isinstance(c, str) else c.decode())
    return "".join(chunks)


def _collect(resp) -> str:
    """Run the async aggregation on a throwaway loop, then restore a fresh
    current loop so deprecated `asyncio.get_event_loop()` callers downstream
    still find one."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_agg(resp))
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_midstream_error_becomes_readable_text():
    out = _collect(_stream_response(_failing_gen()))
    assert "partial answer" in out          # whatever streamed is preserved
    assert "advisor unavailable" in out      # graceful message, not a dropped stream
    assert "boom upstream" in out            # the real reason is surfaced


def test_clean_stream_passes_through_unchanged():
    out = _collect(_stream_response(_clean_gen()))
    assert out == "hello world"


def test_no_buffering_header_set():
    resp = _stream_response(_clean_gen())
    assert resp.headers.get("X-Accel-Buffering") == "no"
