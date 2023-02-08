from collections import deque
from decimal import Decimal
from functools import wraps
from typing import Callable, Literal, Sequence

from alembic import op
from sqlalchemy import Table, event, text
from sqlalchemy.schema import DDL

from app.domain import delivery

from .delivery_orm import delivery_skus

TRIGGER_WHEN = Literal["before", "after"]
TRIGGER_OPTION = Literal["insert", "update", "delete"]


@event.listens_for(delivery.DeliveryOrder, "load")
def receive_load_trx(trx: delivery.DeliveryOrder, _):
    trx.events = deque()


@event.listens_for(delivery.DeliverySku, "load")
def receive_load_sku(sku: delivery.DeliverySku, _):
    sku.events = deque()
    sku.calculated_sku_delivery_fee = Decimal("0")
    sku.calculated_refund_delivery_fee = Decimal("0")


@event.listens_for(delivery.DeliveryPayment, "load")
def receive_load_pmt(pmt: delivery.DeliveryPayment, _):
    pmt.events = deque()


@event.listens_for(delivery.DeliveryPointUnit, "load")
def receive_load_pu(pu: delivery.DeliveryPointUnit, _):
    pu.reserved_amount = Decimal("0")


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
trx_f_update_delivery_product = generate_ddl(
    name="trx_f_update_delivery_product",
    object_type="function",
    trx_product_id="text",
    stmt=(
        """
RETURNS void
AS $$
DECLARE n_product_pv_amount NUMERIC;
        n_number_of_skus_to_consider INT;
        n_number_of_quantity_to_consider INT;
BEGIN
    -- get the aggregated values
    SELECT COALESCE(SUM(s.sku_pv_amount),0),
            COALESCE(COUNT(s.id),0),
            COALESCE(SUM(s.quantity),0)
                INTO
                    n_product_pv_amount,
                    n_number_of_skus_to_consider,
                    n_number_of_quantity_to_consider
    FROM cvm_transaction_delivery_sku AS s
    WHERE s.delivery_product_id::text = trx_product_id AND
            s.sku_pv_amount > 0;

    UPDATE cvm_transaction_delivery_product
        SET product_pv_amount = n_product_pv_amount,
            number_of_skus_to_consider = n_number_of_skus_to_consider,
            number_of_quantity_to_consider = n_number_of_quantity_to_consider,
            curr_calculated_product_delivery_fee = (
                CASE WHEN delivery_pricing_method = 'free' THEN 0 ELSE
                    CASE WHEN n_number_of_skus_to_consider >0 THEN
                        CASE WHEN delivery_pricing_method = 'regular_charge' THEN base_delivery_fee
                             WHEN delivery_pricing_method = 'unit_charge' THEN
                                CASE WHEN n_number_of_skus_to_consider is not null
                                and n_number_of_skus_to_consider !=0 THEN
                                    base_delivery_fee * CEIL(
                                        n_number_of_quantity_to_consider::NUMERIC/charge_standard::NUMERIC
                                    )
                                END
                             WHEN delivery_pricing_method = 'conditional_charge' THEN
                                CASE WHEN n_product_pv_amount >= charge_standard THEN 0
                                ELSE base_delivery_fee
                                END
                             ELSE
                                0
                             END
                        ELSE
                            0
                        END
                END)
    WHERE id::text = trx_product_id;
END;
$$ LANGUAGE plpgsql PARALLEL UNSAFE;
"""
    ),
)

trx_f_update_delivery_product_group_delivery = generate_ddl(
    name="trx_f_update_delivery_product_group_delivery",
    object_type="function",
    delivery_order_group_id="text",
    stmt=(
        """
RETURNS NUMERIC
AS $$
DECLARE
        g_curr_region_additional_delivery_fee NUMERIC;
        -- l_var
        trx_region_id INT;
        g_is_additional_pricing_set BOOLEAN;
        g_region_division_level INT;
        g_division2_fee INT;
        g_division3_jeju_fee INT;
        g_division3_outside_jeju_fee INT;
        g_is_group_delivery BOOLEAN;
        -- aggregate
        g_curr_calculated_group_delivery_fee NUMERIC;
        g_number_of_quantity_to_consider INT;
        g_product_count INT;
        g_curr_group_delivery_discount NUMERIC;
        -- product_info
        p_delivery_pricing_method text;
        p_charge_standard text;
BEGIN
    SELECT
        pgd.region_id::INT,
        pgd.is_additional_pricing_set::BOOLEAN,
        pgd.region_division_level::INT,
        pgd.division2_fee::INT,
        pgd.division3_jeju_fee::INT,
        pgd.division3_outside_jeju_fee::INT,
        (CASE WHEN pgd.supplier_delivery_group_id::TEXT != '' THEN true
                ELSE false
                END) as is_group_delivery,
        SUM(p.curr_calculated_product_delivery_fee),
        SUM(p.number_of_quantity_to_consider),
        SUM(p.curr_calculated_product_delivery_fee) - MAX(p.curr_calculated_product_delivery_fee),
        COUNT(p.id)
        INTO trx_region_id,
                g_is_additional_pricing_set,
                g_region_division_level,
                g_division2_fee,
                g_division3_jeju_fee,
                g_division3_outside_jeju_fee,
                g_is_group_delivery,
                g_curr_calculated_group_delivery_fee,
                g_number_of_quantity_to_consider,
                g_curr_group_delivery_discount,
                g_product_count
    FROM (SELECT *
            FROM cvm_transaction_delivery_group
            WHERE id = delivery_order_group_id
            ) AS pgd
            JOIN
        (SELECT
            inner_p.curr_calculated_product_delivery_fee,
            inner_p.number_of_quantity_to_consider,
            inner_p.delivery_group_id,
            inner_p.delivery_order_id,
            inner_p.id
            FROM cvm_transaction_delivery_product AS inner_p
            ) AS p
            ON pgd.id =  p.delivery_group_id
            JOIN
            (SELECT id
            FROM cvm_transaction_delivery_order
            ) AS trx
            ON p.delivery_order_id = trx.id
    GROUP BY pgd.region_id,
            pgd.is_additional_pricing_set,
            pgd.region_division_level,
            pgd.division2_fee,
            pgd.division3_jeju_fee,
            pgd.division3_outside_jeju_fee,
            is_group_delivery;

    -- Get curr_region_additional_delivery_fee
    g_curr_region_additional_delivery_fee := 0;
    IF g_number_of_quantity_to_consider > 0 THEN
        IF g_is_additional_pricing_set is true THEN
            IF g_region_division_level is null THEN
                g_curr_region_additional_delivery_fee := 0;
            ELSIF g_region_division_level = 2 THEN
                IF trx_region_id = 1 THEN
                    g_curr_region_additional_delivery_fee := 0;
                ELSE
                    g_curr_region_additional_delivery_fee := g_division2_fee;
                END IF ;
            ELSE
                IF trx_region_id = 1 THEN
                    g_curr_region_additional_delivery_fee := 0;
                ELSIF trx_region_id = 2 THEN
                    g_curr_region_additional_delivery_fee := g_division3_jeju_fee;
                ELSE
                    g_curr_region_additional_delivery_fee := g_division3_outside_jeju_fee;
                END IF;
            END IF;
        END IF;
    ELSE
        g_curr_region_additional_delivery_fee := 0;
    END IF;

    -- IF it is single product and it virtually has no group delivery,
    -- calculate region_additional_delivery again.
    IF g_product_count = 1 AND g_is_group_delivery is false THEN
        SELECT delivery_pricing_method::text, charge_standard::text into p_delivery_pricing_method,p_charge_standard
        FROM cvm_transaction_delivery_product p_in_if
        WHERE p_in_if.delivery_group_id = delivery_order_group_id
        LIMIT 1;

        IF p_delivery_pricing_method ='unit_charge' THEN
            g_curr_region_additional_delivery_fee = (
                g_curr_region_additional_delivery_fee *
                ceil(g_number_of_quantity_to_consider::NUMERIC/p_charge_standard::NUMERIC));
        END IF;
    END IF;

    -- set delivery_fee on group delivery entity
    UPDATE cvm_transaction_delivery_group
    SET curr_calculated_group_delivery_fee = g_curr_calculated_group_delivery_fee,
        curr_group_delivery_discount = g_curr_group_delivery_discount,
        curr_region_additional_delivery_fee = g_curr_region_additional_delivery_fee
    WHERE id = delivery_order_group_id;

    RETURN (
        g_curr_calculated_group_delivery_fee
        - g_curr_group_delivery_discount
        + g_curr_region_additional_delivery_fee
    );
END;
$$
LANGUAGE plpgsql PARALLEL UNSAFE;
        """
    ),
)

trx_f_update_transaction = generate_ddl(
    name="trx_f_update_transaction",
    object_type="FUNCTION",
    trx_id="TEXT",
    trx_delivery_fee="NUMERIC",
    stmt=(
        """
RETURNS void
AS $$
BEGIN
    UPDATE cvm_transaction_delivery_order
    SET curr_delivery_order_delivery_fee = trx_delivery_fee,
        curr_delivery_order_pv_amount = (SELECT SUM(sku_pv_amount)
                                    FROM cvm_transaction_delivery_sku s
                                    WHERE s.delivery_order_id = trx_id
                                )
    WHERE id = trx_id;
END;
$$ LANGUAGE plpgsql PARALLEL UNSAFE;
"""
    ),
)

# Trigger function
trx_tf_update_on_sku_status_change_a = generate_ddl(
    name="trx_tf_update_on_sku_status_change_a",
    object_type="function",
    stmt=(
        f"""
RETURNS TRIGGER
AS
$$
BEGIN
    if NEW.status not in (
        {",".join(map(lambda x:f"'{x.value}'",tuple(delivery.DeliverySku._not_countable_statuses)))}) THEN
        NEW.sku_pv_amount := NEW.quantity * NEW.sell_price;
    else NEW.sku_pv_amount:= 0;
end if;
RETURN NEW;
END;
$$
LANGUAGE 'plpgsql' PARALLEL UNSAFE;
"""
    ),
)

trx_tr_update_on_sku_status_change_a = generate_ddl(
    name="trx_tr_update_on_sku_status_change_a",
    object_type="trigger",
    stmt=(
        """
FOR EACH ROW EXECUTE PROCEDURE trx_tf_update_on_sku_status_change_a();
"""
    ),
    trigger_when="before",
    trigger_option="update",
    trigger_of="status",
    trigger_on=delivery_skus.name,
)

trx_tf_update_on_sku_status_change_b = generate_ddl(
    name="trx_tf_update_on_sku_status_change_b",
    object_type="function",
    stmt=(
        """
RETURNS TRIGGER AS $$
DECLARE delivery_product_ids text[];
        delivery_group_ids text[];
        l_id text;
        trx_delivery_fee NUMERIC;
        trx_id text;
BEGIN
        SELECT DISTINCT(delivery_order_id) INTO trx_id FROM new_table;

        SELECT
            ARRAY_AGG(op.id::text) as delivery_product_ids,
            ARRAY_AGG(opgd.id::text) as delivery_group_ids
            INTO delivery_product_ids, delivery_group_ids
        FROM new_table nsku
        JOIN cvm_transaction_delivery_product op
        ON nsku.delivery_product_id = op.id
        LEFT JOIN cvm_transaction_delivery_group opgd
        ON op.delivery_group_id = opgd.id ;

        FOREACH l_id in array delivery_product_ids LOOP
            -- if you want to discard possible return values, use PERFORM
            PERFORM trx_f_update_delivery_product(l_id);
            raise info '%%',l_id;
        END LOOP;

        trx_delivery_fee = 0;
        FOREACH l_id in array delivery_group_ids LOOP
             trx_delivery_fee = trx_delivery_fee + trx_f_update_delivery_product_group_delivery(l_id);
            raise info '%%', l_id;
        END LOOP;
        RAISE INFO '%%', trx_id;
        PERFORM trx_f_update_transaction(trx_id, trx_delivery_fee);
        RETURN NEW;
END;
$$ language plpgsql;
"""
    ),
)

trx_tr_update_on_sku_status_change_b = generate_ddl(
    name="trx_tr_update_on_sku_status_change_b",
    object_type="trigger",
    stmt=(
        """
REFERENCING NEW TABLE as new_table
FOR EACH STATEMENT
EXECUTE FUNCTION trx_tf_update_on_sku_status_change_b();
"""
    ),
    trigger_when="after",
    trigger_option="update",
    trigger_on=delivery_skus.name,
)


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
