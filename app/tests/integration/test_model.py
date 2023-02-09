import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.eventstore import EventStore
from app.tests.fakes import trx_faker

# from sqlalchemy.future import select


def test_hashable():
    json_data = json.loads(trx_faker.json())
    _json_gen = (d for d in json_data)
    aggregate_id = trx_faker.uuid4()
    type_ = trx_faker.word()
    _version = 0
    payment_log1 = EventStore(
        aggregate_id=aggregate_id, aggregate_version=_version, aggregate_type=type_, payload=next(d for d in _json_gen)
    )
    payment_log2 = EventStore(
        aggregate_id=aggregate_id,
        aggregate_version=_version + 1,
        aggregate_type=type_,
        payload=next(d for d in _json_gen),
    )

    dic = {payment_log1, payment_log1, payment_log2}
    assert hash(payment_log1)
    assert payment_log1 != payment_log2
    assert len(dic) == 2


@pytest.mark.asyncio
@pytest.mark.skip("there is no way to test this currently")
async def test_non_relational_mapping(session: AsyncSession):
    ...


def test_repr():
    json_data = json.loads(trx_faker.json())
    payload_ = next(d for d in json_data)
    aggregate_id = trx_faker.uuid4()
    type_ = trx_faker.word()
    _version = 0
    event_store = EventStore(
        aggregate_id=aggregate_id, aggregate_version=_version, aggregate_type=type_, payload=payload_
    )
    assert (
        str(event_store)
        == rf"EventStore(aggregate_id='{aggregate_id}', aggregate_version={_version}, aggregate_type='{type_}'"
        rf", payload={payload_})"
    )
