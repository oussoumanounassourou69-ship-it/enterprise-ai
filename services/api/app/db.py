from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from .config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def db_execute(sql: str, params: dict | list[dict] | None = None):
    async with SessionLocal() as session:
        result = await session.execute(text(sql), params or {})
        await session.commit()
        return result

async def db_fetchall(sql: str, params: dict | None = None):
    async with SessionLocal() as session:
        result = await session.execute(text(sql), params or {})
        return result.mappings().all()

async def db_fetchone(sql: str, params: dict | None = None):
    async with SessionLocal() as session:
        result = await session.execute(text(sql), params or {})
        return result.mappings().first()

async def migrate_chunk_storage():
    async with SessionLocal.begin() as session:
        await session.execute(text('CREATE TABLE IF NOT EXISTS app_schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())'))
        await session.execute(text('ALTER TABLE document_chunks ALTER COLUMN content DROP NOT NULL'))
        result = await session.execute(text('INSERT INTO app_schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING RETURNING version'))
        if result.scalar_one_or_none():
            await session.execute(text('UPDATE document_chunks SET content=NULL WHERE content IS NOT NULL'))
