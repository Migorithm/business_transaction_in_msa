from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.domain.delivery import DeliveryOrder, DeliveryPaymentLog, DeliveryTransaction
from app.tests.fakes import trx_faker


def test_hashable():
    payment_log1 = DeliveryPaymentLog(id=str(uuid4()))
    payment_log2 = DeliveryPaymentLog(id=str(uuid4()))

    dic = {payment_log1, payment_log1, payment_log2}
    assert hash(payment_log1)
    assert payment_log1 != payment_log2
    assert len(dic) == 2


@pytest.mark.asyncio
async def test_non_relational_mapping(session: AsyncSession):
    # Given
    payment_log1 = DeliveryPaymentLog(id=str(uuid4()))
    order_id = str(uuid4())
    order = DeliveryOrder(
        id=order_id,
    )
    transaction = DeliveryTransaction(
        delivery_orders={order},
        id=str(uuid4()),
        country=trx_faker.word(),
        user_id=trx_faker.word(),
        sender_name=trx_faker.word(),
        sender_phone=trx_faker.word(),
        sender_email=trx_faker.word(),
        delivery_note=trx_faker.word(),
        receiver_name=trx_faker.word(),
        receiver_phones=trx_faker.word(),
        receiver_address=trx_faker.word(),
        region_id=1,
        postal_code="123-42",
    )
    order.transaction.payment_logs.add(payment_log1)

    session.add(transaction)

    await session.commit()

    # When
    q = await session.execute(select(DeliveryPaymentLog).limit(1))
    log: DeliveryPaymentLog | None = q.scalars().first()

    # Then
    assert log
    assert log.delivery_transaction_id == order.transaction.id

    # When
    log.delivery_transaction.payment_logs.pop()
    await session.commit()
    q = await session.execute(select(DeliveryPaymentLog).limit(1))
    log2: DeliveryPaymentLog | None = q.scalars().first()

    # Then
    assert log2
    assert log2.delivery_transaction is None
    assert log2.delivery_transaction_id is None


def test_repr():
    id = str(uuid4())
    payment_log = DeliveryPaymentLog(id=id)
    assert str(payment_log) == f"DeliveryPaymentLog(id='{id}', log=" r"{})"


def test_from_kwargs():
    try:
        payment_log = DeliveryPaymentLog.from_kwargs(id=str(uuid4()), whatever="what")
        assert payment_log.whatever == "what"
    except Exception:
        assert 0
