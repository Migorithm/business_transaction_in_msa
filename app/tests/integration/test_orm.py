import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters import delivery_orm, eventstore
from app.adapters.event_listeners import registered_ddls


@pytest.mark.asyncio
async def test_get_table_and_view_names(aio_pg_engine: AsyncEngine):
    def get_table_names(conn):
        inspector = inspect(conn)
        return inspector.get_table_names()

    def get_view_names(conn):
        inspector = inspect(conn)

        return inspector.get_view_names()

    async with aio_pg_engine.connect() as connection:
        table_names = await connection.run_sync(get_table_names)
        for table in delivery_orm.metadata.tables.keys():
            assert table in table_names
        for es_obj in eventstore.metadata.tables.keys():
            assert es_obj in table_names
        view_names = await connection.run_sync(get_view_names)
        for c_view, _ in registered_ddls.get("view", []):
            assert c_view.name in view_names
