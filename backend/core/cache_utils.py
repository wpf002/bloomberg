"""Redis-backed TTL cache for async data-source methods.

- Decorate any async function returning a pydantic model (or list of them).
- Falls back to calling the function directly if Redis is unavailable or
  serialization fails. Never raises because of the cache layer.
- Keys include a short namespace prefix and are prefixed per call signature.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel

from .config import settings
from .database import cache

logger = logging.getLogger(__name__)

T = TypeVar("T")

_SENTINEL = object()


def _hash_args(args: tuple, kwargs: dict) -> str:
    payload = json.dumps({"args": [str(a) for a in args], "kwargs": {k: str(v) for k, v in kwargs.items()}}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _to_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        return json.dumps({"__type__": "model", "data": value.model_dump(mode="json")})
    if isinstance(value, list) and value and isinstance(value[0], BaseModel):
        return json.dumps(
            {"__type__": "model_list", "data": [v.model_dump(mode="json") for v in value]}
        )
    return json.dumps({"__type__": "raw", "data": value})


def _from_json(raw: str, model_type: type | None) -> Any:
    payload = json.loads(raw)
    kind = payload.get("__type__")
    data = payload.get("data")
    if kind == "model" and model_type is not None:
        return model_type.model_validate(data)
    if kind == "model_list" and model_type is not None:
        return [model_type.model_validate(item) for item in data]
    return data


def cached(
    namespace: str,
    ttl: int | None = None,
    model: type[BaseModel] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorate an async method with Redis-backed TTL caching.

    `model` is the pydantic model class the function returns (or the item
    type when it returns a list of models). Required for deserialization.
    """

    ttl_seconds = ttl if ttl is not None else settings.default_cache_ttl

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            client = cache.client
            if client is None:
                return await func(*args, **kwargs)

            signature = _hash_args(args[1:] if args else (), kwargs)  # strip self
            key = f"bt:{namespace}:{signature}"

            try:
                hit = await client.get(key)
            except Exception as exc:  # redis fault → degrade
                logger.debug("cache get failed: %s", exc)
                hit = None

            if hit is not None:
                try:
                    return _from_json(hit, model)
                except Exception as exc:
                    logger.debug("cache deserialize failed for %s: %s", key, exc)

            result = await func(*args, **kwargs)

            try:
                await client.setex(key, ttl_seconds, _to_json(result))
            except Exception as exc:
                logger.debug("cache set failed: %s", exc)

            return result

        return wrapper

    return decorator
