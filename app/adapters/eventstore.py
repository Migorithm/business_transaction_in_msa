from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Column, Index, Integer, MetaData, Numeric, Sequence, String, Table, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import registry

NUMERIC = Numeric(19, 4)
metadata = MetaData()
mapper_registry = registry(metadata=metadata)


global_seq: Sequence = Sequence("global_seq_on_event_store", metadata=mapper_registry.metadata)
event_store = Table(
    "cvm_transaction_event_store",
    mapper_registry.metadata,
    Column("global_seq", Integer, global_seq, server_default=global_seq.next_value(), primary_key=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column("aggregate_id", String, nullable=False),
    Column("aggregate_version", Integer, nullable=False, unique=True),
    Column("aggregate_type", String, nullable=False),
    Column("payload", postgresql.JSONB, nullable=False),
)

idx_on_event_store = Index("idx_on_event_store", event_store.c.aggregate_id, event_store.c.aggregate_version)


@dataclass(eq=False)
class EventStore:
    global_seq: int = field(init=False, repr=False)
    create_dt: datetime = field(init=False, repr=False)
    aggregate_id: str
    aggregate_version: int
    aggregate_type: str
    payload: dict = field(default_factory=dict)


def start_mappers():
    mapper_registry.map_imperatively(
        EventStore, event_store, eager_defaults=True, version_id_col=event_store.c.global_seq
    )
