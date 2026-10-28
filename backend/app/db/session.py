"""Async engine and sessions. Writes: `async with session() as s, s.begin(): ...`; reads: `async with read_session() as s:`.

SQLite (local development and tests) runs in WAL mode with foreign keys on. Write transactions start with
BEGIN IMMEDIATE, so concurrent writers queue on the lock (busy_timeout) instead of failing a read-to-write upgrade.
Read-only sessions start DEFERRED: under WAL a reader never takes the write lock, so heavy polling cannot starve a
run's writes (it did, as "database is locked", before reads were split out).
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

READ_ONLY = "nativeproof_read_only"

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_read_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def make_engine(url: str) -> AsyncEngine:
    # No pre-ping: each one costs a full round trip (about 410 ms to Supabase from outside its region), and asyncpg
    # reports a dead connection anyway. Recycling keeps pooled connections fresh.
    engine = create_async_engine(url, pool_recycle=1800)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _configure(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
            dbapi_connection.isolation_level = None  # SQLAlchemy emits BEGIN itself (below)
            cursor = dbapi_connection.cursor()
            for pragma in ("journal_mode=WAL", "foreign_keys=ON", "busy_timeout=5000", "synchronous=NORMAL"):
                cursor.execute(f"PRAGMA {pragma}")
            cursor.close()

        @event.listens_for(engine.sync_engine, "begin")
        def _begin(connection) -> None:  # type: ignore[no-untyped-def]
            read_only = connection.get_execution_options().get(READ_ONLY, False)
            connection.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")

    return engine


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker, _read_sessionmaker
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        _read_sessionmaker = async_sessionmaker(_engine.execution_options(**{READ_ONLY: True}), expire_on_commit=False)
    return _engine


def session() -> AsyncSession:
    """A session for work that writes (or may write)."""
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker()


def read_session() -> AsyncSession:
    """A session for read-only work. Never write through it."""
    get_engine()
    assert _read_sessionmaker is not None
    return _read_sessionmaker()


async def dispose_engine() -> None:
    global _engine, _sessionmaker, _read_sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker, _read_sessionmaker = None, None, None
