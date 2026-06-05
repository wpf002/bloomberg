"""Per-user broker credential storage (encrypted).

Secrets are encrypted with core/encryption before they touch Postgres and are
only ever decrypted in-process by the resolver. The list/read API returns
masked metadata only (broker, mode, key last-4, updated_at) — never plaintext.
"""

from __future__ import annotations

import logging

from ..database import database
from ..encryption import decrypt, encrypt

logger = logging.getLogger(__name__)


async def save_credentials(user_id: int, broker: str, mode: str, key: str, secret: str) -> dict:
    """Encrypt + upsert one (user, broker, mode) credential row."""
    if database.pool is None:
        raise RuntimeError("database unavailable")
    enc_key = encrypt(key)
    enc_secret = encrypt(secret)
    last4 = key[-4:] if key else ""
    async with database.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_broker_credentials
                (user_id, broker_name, mode, enc_key, enc_secret, key_last4, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,NOW())
            ON CONFLICT (user_id, broker_name, mode) DO UPDATE SET
                enc_key = EXCLUDED.enc_key,
                enc_secret = EXCLUDED.enc_secret,
                key_last4 = EXCLUDED.key_last4,
                updated_at = NOW()
            """,
            user_id, broker, mode, enc_key, enc_secret, last4,
        )
    return {"broker": broker, "mode": mode, "configured": True, "key_last4": last4}


async def list_credentials(user_id: int) -> list[dict]:
    """Masked view of which (broker, mode) slots the user has configured."""
    if database.pool is None:
        return []
    async with database.acquire() as conn:
        rows = await conn.fetch(
            "SELECT broker_name, mode, key_last4, updated_at "
            "FROM user_broker_credentials WHERE user_id=$1 ORDER BY broker_name, mode",
            user_id,
        )
    return [
        {
            "broker": r["broker_name"],
            "mode": r["mode"],
            "configured": True,
            "key_last4": r["key_last4"] or "",
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


async def delete_credentials(user_id: int, broker: str, mode: str) -> bool:
    if database.pool is None:
        return False
    async with database.acquire() as conn:
        out = await conn.execute(
            "DELETE FROM user_broker_credentials WHERE user_id=$1 AND broker_name=$2 AND mode=$3",
            user_id, broker, mode,
        )
    return bool(out and out.endswith(" 1"))


async def get_decrypted(user_id: int | None, broker: str, mode: str) -> tuple[str, str] | None:
    """Return (api_key, api_secret) for the slot, or None if not set / no DB."""
    if user_id is None or database.pool is None:
        return None
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT enc_key, enc_secret FROM user_broker_credentials "
            "WHERE user_id=$1 AND broker_name=$2 AND mode=$3",
            user_id, broker, mode,
        )
    if not row:
        return None
    try:
        return decrypt(row["enc_key"]), decrypt(row["enc_secret"])
    except Exception as exc:
        logger.warning("broker cred decrypt failed for user=%s %s/%s: %s", user_id, broker, mode, exc)
        return None
