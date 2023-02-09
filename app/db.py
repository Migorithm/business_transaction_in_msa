from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.adapters import eventstore  # ,delivery_orm, service_orm
from app.config import PERSISTENT_DB, STAGE

engine: AsyncEngine | None = None
autocommit_engine: AsyncEngine | None = None
async_transactional_session_factory: sessionmaker | None = None
async_autocommit_session_factory: sessionmaker | None = None

if STAGE not in ("testing", "ci-testing"):
    engine = create_async_engine(
        PERSISTENT_DB.get_uri(), pool_pre_ping=True, pool_size=10, max_overflow=20, future=True
    )
    async_transactional_session_factory = sessionmaker(
        engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    async_autocommit_session_factory = sessionmaker(autocommit_engine, expire_on_commit=False, class_=AsyncSession)
    eventstore.start_mappers()
    # delivery_orm.start_mappers()
    # service_orm.start_mappers()
