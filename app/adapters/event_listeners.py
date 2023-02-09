from functools import wraps
from typing import Callable, Literal, Sequence

from alembic import op
from sqlalchemy import Table, event, text
from sqlalchemy.schema import DDL

TRIGGER_WHEN = Literal["before", "after"]
TRIGGER_OPTION = Literal["insert", "update", "delete"]


# @event.listens_for(delivery.DeliveryOrder, "load")
# def receive_load_trx(trx: delivery.DeliveryOrder, _):
#     trx.events = deque()


# @event.listens_for(delivery.DeliverySku, "load")
# def receive_load_sku(sku: delivery.DeliverySku, _):
#     sku.events = deque()
#     sku.calculated_sku_delivery_fee = Decimal("0")
#     sku.calculated_refund_delivery_fee = Decimal("0")


# @event.listens_for(delivery.DeliveryPayment, "load")
# def receive_load_pmt(pmt: delivery.DeliveryPayment, _):
#     pmt.events = deque()


# @event.listens_for(delivery.DeliveryPointUnit, "load")
# def receive_load_pu(pu: delivery.DeliveryPointUnit, _):
#     pu.reserved_amount = Decimal("0")


registered_ddls: dict[Literal["view", "function", "trigger"], list] = dict()


def register_ddls(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        create_ddl, drop_ddl = func(*args, **kwargs)
        create_ddl.name = kwargs["name"]
        registered_ddls.setdefault(kwargs["object_type"], []).append((create_ddl, drop_ddl))

    return wrapped


@register_ddls
def generate_ddl(
    *,
    object_type: str,
    name: str,
    stmt: str,
    trigger_when: TRIGGER_WHEN | None = None,
    trigger_option: Sequence[TRIGGER_OPTION] | TRIGGER_OPTION | None = None,
    trigger_of: Sequence[str] | str | None = None,
    trigger_on: str | None = None,
    **kwargs,
) -> tuple[DDL, DDL]:
    create_format: Callable | None = None
    drop_format: Callable | None = None
    match object_type.upper():
        case "VIEW":
            create_format = "CREATE OR REPLACE {} {} AS {}".format
            drop_format = "DROP {} IF EXISTS {}".format
        case "PROCEDURE" | "FUNCTION":
            temp_format = "CREATE OR REPLACE {} {}(%s) {}" % (",".join([f"{k} {v}" for k, v, in kwargs.items()]))
            create_format = temp_format.format
            drop_format = "DROP {} IF EXISTS {} CASCADE".format
        case "TRIGGER":
            if not all((trigger_option, trigger_when, trigger_on)):
                raise Exception
            assert trigger_option

            temp_format = "CREATE OR REPLACE {} {} %s %s" % (
                trigger_when,
                " OR ".join(trigger_option if not isinstance(trigger_option, str) else [trigger_option]),
            )
            if trigger_of:
                temp_format += " OF %s " % ",".join(trigger_of if not isinstance(trigger_of, str) else [trigger_of])
            temp_format += f" ON {trigger_on}"
            temp_format += "{}"
            create_format = temp_format.format

            drop_temp_format = "DROP {} IF EXISTS {} ON %s CASCADE;" % (trigger_on)
            drop_format = drop_temp_format.format
        case _:
            raise Exception

    create_view_ddl = DDL(create_format(object_type.upper(), name, stmt)).execute_if(dialect=("postgresql", "sqlite"))
    drop_view_ddl = DDL(drop_format(object_type.upper(), name)).execute_if(dialect="postgresql")
    return create_view_ddl, drop_view_ddl


# Data Modifying function
def run_replaceable_object_migration():
    ddls = []
    for _, ddls_ in registered_ddls.items():
        ddls += ddls_
    for c_ddl, d_ddl in ddls:
        event.listen(Table, "before_drop", d_ddl)
        d_ddl(target=None, bind=op.get_bind())

        event.listen(Table, "after_create", c_ddl)
        c_ddl(target=None, bind=op.get_bind())


def drop_all_replaceable_object():
    op.execute(
        text(
            """
        call drop_all_db_objects();
        """
        )
    )
