from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
