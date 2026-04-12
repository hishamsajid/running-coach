"""PostgreSQL persistence for chat history.

Uses asyncpg for async database access. If DATABASE_URL is not set,
all functions are no-ops and the bot falls back to in-memory history.
"""
import json
import logging
import os

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS chat_history (
        chat_id BIGINT PRIMARY KEY,
        messages JSONB NOT NULL DEFAULT '[]',
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
"""


def is_available() -> bool:
    return _pool is not None


async def init_pool():
    """Create the connection pool and ensure the schema exists."""
    global _pool
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.warning("DATABASE_URL not set — chat history will not persist across restarts")
        return
    _pool = await asyncpg.create_pool(database_url)
    async with _pool.acquire() as conn:
        await conn.execute(_CREATE_TABLE)
    logger.info("Database pool initialised")


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def load_history(chat_id: int) -> list:
    """Return the stored message history for a chat, or [] if none."""
    if not _pool:
        return []
    row = await _pool.fetchrow(
        "SELECT messages FROM chat_history WHERE chat_id = $1", chat_id
    )
    return json.loads(row["messages"]) if row else []


async def save_history(chat_id: int, messages: list):
    """Upsert the message history for a chat."""
    if not _pool:
        return
    await _pool.execute(
        """
        INSERT INTO chat_history (chat_id, messages, updated_at)
        VALUES ($1, $2::jsonb, NOW())
        ON CONFLICT (chat_id) DO UPDATE
            SET messages = $2::jsonb, updated_at = NOW()
        """,
        chat_id,
        json.dumps(messages),
    )


async def clear_history(chat_id: int):
    """Delete the stored history for a chat."""
    if not _pool:
        return
    await _pool.execute(
        "DELETE FROM chat_history WHERE chat_id = $1", chat_id
    )
