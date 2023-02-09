import asyncio
import sys

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import clear_mappers, sessionmaker

from app.adapters.delivery_orm import metadata as delivery_metadata

# from app.adapters.delivery_orm import start_mappers as delivery_start_mappers
from app.adapters.event_listeners import registered_ddls
from app.adapters.eventstore import metadata as es_metadata
from app.adapters.eventstore import start_mappers as es_start_mappers
from app.adapters.service_orm import metadata as service_metadata

# from app.adapters.service_orm import start_mappers as service_start_mappers
from app.config import PERSISTENT_DB

create_drop_procedure = """
CREATE OR REPLACE PROCEDURE drop_all_db_objects()
AS $$
    DECLARE v_rec record;
            v_schema_obj text;
            f_rec record;
            f_schema_obj text;
            tr_rec record;
            tr_schema_obj text;
    BEGIN
        FOR v_rec in (SELECT table_name FROM information_schema.views where table_schema = 'public') LOOP
            v_schema_obj := concat('public.',v_rec.table_name);
            EXECUTE format(
                'DROP VIEW IF EXISTS %s;', v_schema_obj
            );
        END LOOP;

        FOR tr_rec in (
            SELECT trigger_name,event_object_table
            FROM information_schema.triggers as tri where tri.trigger_schema ='public'
            ) LOOP
            tr_schema_obj := (tr_rec.trigger_name || ' ON ' ||  tr_rec.event_object_table );
            EXECUTE format(
                'DROP TRIGGER IF EXISTS %s CASCADE;', tr_schema_obj
            );
        END LOOP;

        FOR f_rec in (
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_schema='public' and routine_type='FUNCTION' and routine_name like 'trx_%'
            ) LOOP
            f_schema_obj := concat('public.',f_rec.routine_name);
            EXECUTE format(
                'DROP FUNCTION IF EXISTS %s CASCADE;', f_schema_obj
            );
        END LOOP;

END;

$$ language plpgsql;
"""


@pytest.fixture(scope="session")
def event_loop():
    """
    Creates an instance of the default event loop for the test session
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    if sys.platform.startswith("win") and sys.version_info[:2] >= (3, 8):
        # Avoid "RuntimeError: Event loop is closed" on Windows when tearing down tests
        # https://github.com/encode/httpx/issues/914
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def aio_pg_engine():
    engine = create_async_engine(
        PERSISTENT_DB.get_test_uri(),
        future=True,  # poolclass=NullPool
    )
    async with engine.begin() as conn:
        drop_stmt = f"DROP TABLE IF EXISTS {','.join(delivery_metadata.tables.keys())},\
            {','.join(service_metadata.tables.keys())},{','.join(es_metadata.tables.keys())} CASCADE;"
        await conn.execute(text(drop_stmt))

        await conn.execute(text(create_drop_procedure))
        await conn.execute(
            text(
                """
        call drop_all_db_objects();
        """
            )
        )

        for _, list_ in registered_ddls.items():
            for c_ddl, _ in list_:
                event.listen(delivery_metadata, "after_create", c_ddl)
                # await conn.execute(text(c_ddl.statement.replace(r"%%",r"%")))

        await conn.run_sync(delivery_metadata.create_all)
        await conn.run_sync(service_metadata.create_all)
        await conn.run_sync(es_metadata.create_all)

    # delivery_start_mappers()
    # service_start_mappers()
    es_start_mappers()

    yield engine

    clear_mappers()
    # engine.sync_engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(aio_pg_engine: AsyncEngine):
    _session_factory: sessionmaker = sessionmaker(
        aio_pg_engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    yield _session_factory


@pytest_asyncio.fixture(scope="function")
async def session(session_factory: sessionmaker):
    async with session_factory() as session_:
        yield session_
        for delivery_tb in delivery_metadata.tables.keys():
            truncate_stmt = f"DELETE FROM {delivery_tb};"
            # truncate_stmt = f"TRUNCATE TABLE {delivery_tb} CASCADE;"
            await session_.execute(text(truncate_stmt))

        for service_tb in service_metadata.tables.keys():
            truncate_stmt = f"DELETE FROM {service_tb};"
            # truncate_stmt = f"TRUNCATE TABLE {service_tb} CASCADE;"
            await session_.execute(text(truncate_stmt))
        await session_.commit()


@pytest_asyncio.fixture(scope="function")
async def secondary_transactional_session(aio_pg_engine: AsyncEngine):
    SessionFactory: sessionmaker = sessionmaker(
        aio_pg_engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    async with SessionFactory() as session_:
        yield session_
        for delivery_tb in delivery_metadata.tables.keys():
            truncate_stmt = f"DELETE FROM {delivery_tb};"
            # truncate_stmt = f"TRUNCATE TABLE {delivery_tb} CASCADE;"
            await session_.execute(text(truncate_stmt))

        for service_tb in service_metadata.tables.keys():
            truncate_stmt = f"DELETE FROM {service_tb};"
            # truncate_stmt = f"TRUNCATE TABLE {service_tb} CASCADE;"
            await session_.execute(text(truncate_stmt))


@pytest_asyncio.fixture(scope="function")
async def autocommit_session_factory(aio_pg_engine: AsyncEngine):
    autocommit_engine = aio_pg_engine.execution_options(isolation_level="AUTOCOMMIT")
    SessionFactory: sessionmaker = sessionmaker(
        autocommit_engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    yield SessionFactory


@pytest_asyncio.fixture(scope="function")
async def autocommit_session(autocommit_session_factory: sessionmaker):
    async with autocommit_session_factory() as session_:
        yield session_
        await session_.close()
