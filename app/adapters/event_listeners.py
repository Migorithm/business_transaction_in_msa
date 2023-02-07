from collections import deque
from decimal import Decimal
from functools import wraps
from typing import Callable, Literal, Sequence

from alembic import op
from sqlalchemy import Table, event, text
from sqlalchemy.schema import DDL

from app.domain import delivery

from .delivery_orm import (
    delivery_groups,
    delivery_orders,
    delivery_payment_refunds,
    delivery_payments,
    delivery_point_units,
    delivery_products,
    delivery_sku_logs,
    delivery_skus,
    delivery_transactions,
)

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


# View
trx_v_delivery_sku_logs_for_backoffice = generate_ddl(
    name="trx_v_delivery_sku_logs_for_backoffice",
    object_type="view",
    stmt=f"""
    SELECT
    sl.*,
    t.sender_name,
    t.sender_phone,
    t.sender_email,
    t.receiver_name,
    t.receiver_phones,
    t.receiver_address,
    t.postal_code,
    t.delivery_note,
    s.delivery_product_id,
    s.product_title,
    s.status as sku_status,
    s.quantity,
    s.title AS sku_title,
    s.country,
    s.seller_portal_id
    FROM {delivery_transactions.name} t
    JOIN {delivery_skus.name} s
    ON t.id = s.delivery_transaction_id
    JOIN {delivery_sku_logs.name} sl
    ON s.id = sl.delivery_sku_id
    """,
)

trx_v_delivery_sku_log_status_count = generate_ddl(
    name="trx_v_delivery_sku_log_status_count",
    object_type="view",
    stmt=f"""
    SELECT l.id, l.status, l.channel_portal_id FROM (
            SELECT * FROM {delivery_skus.name} AS isku
            WHERE isku.status in (
                'refund_requested',
                'refund_inspect_pass',
                'exchange_requested',
                'order_fail_check_rejected',
                'order_fail_ship_rejected'
                )
        ) AS s
        INNER JOIN LATERAL (
            SELECT * FROM {delivery_sku_logs.name} AS ilog
            WHERE ilog.status in (
            'refund_requested',
            'exchange_requested',
            'order_fail_check_rejected',
            'order_fail_ship_rejected'
            )
            AND (
                (s.status = 'refund_requested' AND ilog.status = 'refund_requested')
                OR (s.status = 'refund_inspect_pass' AND ilog.status = 'refund_requested')
                OR (s.status = 'exchange_requested' AND ilog.status = 'exchange_requested')
                OR (s.status = 'order_fail_check_rejected' AND ilog.status = 'order_fail_check_rejected')
                OR (s.status = 'order_fail_ship_rejected' AND ilog.status = 'order_fail_ship_rejected')
            )
        ) AS l
        ON s.id = l.delivery_sku_id
    """,
)

#
# * Excel view do
trx_v_excel_do = generate_ddl(
    name="trx_v_excel_do",
    object_type="view",
    stmt=f"""
    SELECT
        t.create_dt,
        t.channel_name,
        o.id as delivery_order_id,
        pgd.supplier_delivery_group_name,
        p.id as delivery_product_id,
        p.master_product_sn,
        p.title as product_title,
        s.id,
        s.title as sku_title,
        s.quantity,
        s.sell_price*s.quantity as sku_pv_amount,
        s.cost,
        s.supply_price,
        t.sender_name,
        t.sender_phone,
        t.receiver_name,
        t.receiver_phones,
        t.receiver_address,
        t.postal_code,
        t.delivery_note,
        s.status as status,
        s.supplier_portal_id,
        s.update_dt
    FROM {delivery_transactions.name} t
    JOIN {delivery_orders.name} o
    ON t.id = o.delivery_transaction_id
    JOIN {delivery_skus.name} s
    ON o.id = s.delivery_order_id
    JOIN {delivery_products.name} p
    ON s.delivery_product_id = p.id
    JOIN {delivery_groups.name} pgd
    ON p.delivery_group_id = pgd.id
    """,
)

# ! aggregate sum?
trx_v_excel_so_my_channel_order = generate_ddl(
    name="trx_v_excel_so_my_channel_order",
    object_type="view",
    stmt=(
        f"""
    SELECT
        t.create_dt,
        s.channel_name,
        s.country,
        t.id AS delivery_transaction_id,
        o.id AS delivery_order_id,
        t.sender_name,
        t.sender_phone,
        t.receiver_name,
        t.receiver_phones,
        t.receiver_address,
        t.delivery_note,
        s.carrier_code,
        s.carrier_number,
        tp.init_pg_amount,
        t.status AS trx_status,
        tp.curr_pg_amount AS curr_pg_amount,
        (SELECT SUM(init_delivery_order_delivery_fee) FROM {delivery_orders.name} WHERE id = o.id)
        AS init_delivery_order_delivery_fee,
        (SELECT SUM(curr_delivery_order_delivery_fee) FROM {delivery_orders.name} WHERE id = o.id)
        AS curr_delivery_order_delivery_fee,
        pgd.curr_calculated_group_delivery_fee,
        pgd.curr_region_additional_delivery_fee,
        pgd.curr_group_delivery_discount,
        pgd.supplier_delivery_group_name AS group_name,
        (
            pgd.curr_calculated_group_delivery_fee
            - pgd.curr_group_delivery_discount
            + pgd.curr_region_additional_delivery_fee
        )
        AS group_delivery_fee,
        p.id delivery_product_id,
        p.master_product_sn,
        p.sellable_product_sn,
        p.title AS product_title,
        p.is_vat,
        p.supplier_name,
        p.seller_name,
        p.delivery_pricing_unit,
        p.delivery_pricing_method,
        p.curr_calculated_product_delivery_fee,
        s.id AS delivery_sku_id,
        s.title AS sku_title,
        s.sell_price,
        s.quantity,
        s.sku_pv_amount,
        (SELECT sum(curr_point_amount) FROM {delivery_point_units.name} pu WHERE pu.delivery_sku_id = s.id)
        AS point_paid_amount,
        s.status,
        s.supply_price,
        s.base_delivery_fee,
        s.channel_commission_rate,
        p.refund_delivery_fee,
        p.exchange_delivery_fee,
        s.accumulated_delivery_fee,
        p.supplier_portal_id,
        p.seller_portal_id,
        p.channel_portal_id,
        t.channel_id

        FROM  {delivery_transactions.name} t
        JOIN {delivery_orders.name} o ON o.delivery_transaction_id = t.id
        JOIN {delivery_skus.name} s ON o.id = s.delivery_order_id
        JOIN {delivery_products.name} p on p.id = s.delivery_product_id
        JOIN {delivery_groups.name} pgd on pgd.id = p.delivery_group_id
        JOIN {delivery_payments.name} tp ON tp.delivery_transaction_id = pgd.delivery_transaction_id

    """
    ),
)


trx_v_excel_so_other_channel_order = generate_ddl(
    object_type="view",
    name="trx_v_excel_so_other_channel_order",
    stmt=(
        f"""
    SELECT
        t.create_dt,
        t.channel_name,
        t.country,
        t.id AS delivery_transaction_id,
        t.sender_name,
        t.sender_phone,
        t.receiver_name,
        t.receiver_phones,
        t.receiver_address,
        t.delivery_note,
        t.status AS transaction_status,
        o.id AS delivery_order_id,
        (SELECT SUM(curr_delivery_order_pv_amount)
            FROM {delivery_orders.name}
            WHERE delivery_transaction_id = t.id) +
        (SELECT SUM(curr_delivery_order_delivery_fee)
            FROM {delivery_orders.name}
            WHERE delivery_transaction_id = t.id)
        AS net_paid_amount,

        (SELECT SUM(curr_delivery_order_delivery_fee)
            FROM {delivery_orders.name}
            WHERE delivery_transaction_id = t.id)
        AS curr_delivery_order_delivery_fee,
        (SELECT SUM(init_delivery_order_pv_amount)
            FROM {delivery_orders.name}
            WHERE delivery_transaction_id = t.id)
        AS init_delivery_order_pv_amount,
        (SELECT SUM(init_delivery_order_delivery_fee)
            FROM {delivery_orders.name}
            WHERE delivery_transaction_id = t.id)
        AS init_delivery_order_delivery_fee,

        (SELECT SUM(curr_calculated_group_delivery_fee)
            FROM {delivery_groups.name} as ig
            WHERE ig.delivery_transaction_id = t.id)
        AS calculated_group_delivery_fee_in_total,
        (SELECT SUM(curr_region_additional_delivery_fee)
            FROM {delivery_groups.name} as ig
            WHERE ig.delivery_transaction_id = t.id)
        AS region_additional_delivery_fee_in_total,
        (SELECT SUM(curr_group_delivery_discount)
            FROM {delivery_groups.name} as ig
            WHERE ig.delivery_transaction_id = t.id)
        AS group_delivery_discount_in_total,
        pgd.supplier_delivery_group_name AS group_name,
        (pgd.curr_calculated_group_delivery_fee -
        pgd.curr_group_delivery_discount +
        pgd.curr_region_additional_delivery_fee)
        AS group_delivery_fee,
        p.id AS delivery_product_id,
        p.master_product_sn,
        p.sellable_product_sn,
        p.title AS product_title,
        p.is_vat,
        p.supplier_name,
        p.seller_name,
        p.delivery_pricing_unit,
        p.delivery_pricing_method,
        p.curr_calculated_product_delivery_fee,
        s.id AS delivery_sku_id,
        s.title AS sku_title,
        s.sell_price,
        s.quantity,
        s.sku_pv_amount,
        s.status AS sku_status,
        s.carrier_code,
        s.carrier_number,
        s.cost,
        s.supply_price,
        p.base_delivery_fee,
        p.refund_delivery_fee,
        p.exchange_delivery_fee,
        p.supplier_portal_id,
        p.seller_portal_id,
        p.channel_portal_id,
        t.channel_id
    FROM {delivery_transactions} t
    JOIN {delivery_orders.name} o ON t.id = o.delivery_transaction_id
    JOIN {delivery_skus.name} s ON s.delivery_order_id = o.id
    JOIN {delivery_products.name} p on p.id = s.delivery_product_id
    JOIN {delivery_groups.name} pgd on pgd.id = p.delivery_group_id

    """
    ),
)


trx_v_payment_info = generate_ddl(
    object_type="view",
    name="trx_v_payment_info",
    stmt=(
        f"""
    SELECT
        t.id AS delivery_transaction_id,
        tp.id AS delivery_payment_id,
        t.create_dt,
        t.channel_portal_id,
        SUM(CASE WHEN pu.point_unit_type = 't' then pu.init_point_amount ELSE 0 END)
        AS init_transactional_point,
        SUM(CASE WHEN pu.point_unit_type = 's' then pu.init_point_amount ELSE 0 END)
        AS init_sku_point,
        tp.init_coupon_amount,
        tp.init_pg_amount
    FROM
        {delivery_transactions.name} t
        JOIN {delivery_payments} tp ON t.id = tp.delivery_transaction_id
        LEFT JOIN {delivery_point_units} pu ON tp.delivery_transaction_id = pu.delivery_transaction_id
    GROUP BY t.id, tp.id
    """
    ),
)

trx_v_payment_refund_info = generate_ddl(
    object_type="view",
    name="trx_v_payment_refund_info",
    stmt=(
        f"""
    SELECT
        rf.refund_context_sku_id AS refund_context_sku_id,
        t.id AS delivery_transaction_id,
        t.channel_portal_id,
        TO_TIMESTAMP(AVG(EXTRACT(EPOCH FROM rf.create_dt)::float))
        AS create_dt,
        SUM(CASE WHEN rf.delivery_sku_id is null then rf.point_amount_for_refund ELSE 0 END)
        AS transactional_point,
        SUM(CASE WHEN rf.delivery_sku_id is not null then rf.point_amount_for_refund ELSE 0 END)
        AS sku_point,
        SUM(CASE WHEN rf.delivery_sku_id is null then rf.coupon_amount_for_refund ELSE 0 END)
        AS transactional_coupon,
        SUM(CASE WHEN rf.delivery_sku_id is null then rf.coupon_amount_for_refund ELSE 0 END)
        AS sku_coupon,
        SUM(rf.pg_amount_for_refund) AS pg_amount_for_refund
    FROM
        {delivery_transactions.name} t
        JOIN {delivery_payment_refunds.name} rf ON t.id = rf.delivery_transaction_id
    GROUP BY rf.refund_context_sku_id,rf.create_dt, t.id
    """
    ),
)

trx_v_for_product_disbursement = generate_ddl(
    name="trx_v_for_product_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        sku.id,
        delivery_order.create_dt AS order_processed_date,
        sku.purchased_finalized_date AS order_confirm_date,
        sku.channel_id,
        sku.channel_name,
        sku.channel_portal_id,
        sku.supplier_portal_id,
        sku.seller_portal_id,
        sku.supplier_name,
        sku.seller_name,
        trx.id AS delivery_order_id,
        product.id AS delivery_product_id,
        sku.id AS delivery_sku_id,
        product.title AS product_name,
        sku.title AS sku_name,
        sku.supply_price,
        sku.sell_price,
        sku.sell_price * sku.quantity AS total_sell_price,
        sku.quantity,
        sku.pg_commission_rate,
        sku.channel_commission_rate,
        sku.seller_commission_rate,
        sku.cvm_commission_rate,
        sku.channel_commission_price,
        sku.seller_commission_price,
        sku.pg_commission_price,
        sku.cvm_commission_price,
        (sku.channel_commission_price + sku.seller_commission_price
        + sku.pg_commission_price + sku.cvm_commission_price) AS total_commission_price,
        CASE
            WHEN sku.supplier_portal_id = sku.seller_portal_id THEN (
                sku.channel_commission_price
                + sku.seller_commission_price
                + sku.pg_commission_price
                + sku.cvm_commission_price
            )
            ELSE (
                sku.channel_commission_price + sku.pg_commission_price + sku.cvm_commission_price
            )
        END AS total_commission_by_supplier,
        CASE
            WHEN sku.supplier_portal_id = sku.seller_portal_id THEN (
                (sku.sell_price * sku.quantity) - (
                    sku.channel_commission_price
                    + sku.seller_commission_price
                    + sku.pg_commission_price
                    + sku.cvm_commission_price
                )
            )
            ELSE (
                (sku.sell_price * sku.quantity) - (
                    sku.channel_commission_price
                    + sku.pg_commission_price
                    + sku.cvm_commission_price
                )
            )
        END AS disbursement_price,
        trx.sender_name,
        trx.sender_phone,
        trx.receiver_address,
        product.product_class,
        product.country,
        trx.currency,
        product.is_vat,
        sku.timesale_applied,
        sku.disbursement_expecting_start_date,
        sku.disbursement_expecting_end_date,
        sku.disbursement_status,
        sku.disbursement_complete_date,
        sku.monthly_product_disbursement_id AS monthly_id
    FROM {delivery_skus.name} AS sku
        JOIN {delivery_orders.name} delivery_order ON sku.delivery_order_id = delivery_order.id
        JOIN {delivery_transactions.name} trx ON delivery_order.delivery_transaction_id = trx.id
        JOIN {delivery_products.name} product ON sku.delivery_product_id = product.id
    WHERE sku.disbursement_status IS NOT NULL
    """,
)

trx_v_for_shipping_disbursement = generate_ddl(
    name="trx_v_for_shipping_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        group_delivery.id,
        group_delivery.disbursement_expecting_start_date,
        group_delivery.disbursement_expecting_end_date,
        group_delivery.disbursement_complete_date,
        delivery_order.id as delivery_order_id,
        delivery_order.create_dt as order_processed_date,
        delivery_transaction.sender_name,
        delivery_transaction.sender_phone,
        delivery_transaction.receiver_address,
        delivery_transaction.postal_code,
        group_delivery.supplier_delivery_group_name as group_name,
        group_delivery.channel_id,
        group_delivery.channel_portal_id,
        group_delivery.channel_name,
        group_delivery.supplier_portal_id,
        group_delivery.supplier_name,
        (
            group_delivery.curr_calculated_group_delivery_fee
            + group_delivery.curr_region_additional_delivery_fee
            - group_delivery.curr_group_delivery_discount
        ) AS applied_delivery_fee,
        group_delivery.init_calculated_group_delivery_fee as origin_total_delivery_fee,
        group_delivery.curr_calculated_group_delivery_fee as total_delivery_fee,
        group_delivery.curr_region_additional_delivery_fee as region_additional_delivery_fee,
        group_delivery.curr_group_delivery_discount as group_delivery_discount,
        delivery_order.country,
        delivery_order.currency,
        group_delivery.disbursement_status,
        sku_aggr.extra_delivery_fee,
        (
            group_delivery.curr_calculated_group_delivery_fee
            + group_delivery.curr_region_additional_delivery_fee
            - group_delivery.curr_group_delivery_discount
            + sku_aggr.extra_delivery_fee
            - group_delivery.loss_fee
        ) disbursement_price,
        group_delivery.monthly_shipping_disbursement_id AS monthly_id,
        delivery_transaction.id AS transaction_id
    FROM {delivery_groups.name} AS group_delivery
        JOIN {delivery_orders.name} delivery_order ON  delivery_order.id = group_delivery.delivery_order_id
        JOIN {delivery_transactions.name} delivery_transaction
        ON  delivery_transaction.id = delivery_order.delivery_transaction_id
        JOIN (
            select sub_q_product.delivery_group_id as pgd_id,
                   sum(
                        coalesce(sub_q_sku.accumulated_delivery_fee
                        -> 'accumulated_exchange_delivery_fee_for_channel_owner', '0.0000')::numeric(19,4)
                        + coalesce(sub_q_sku.accumulated_delivery_fee
                        -> 'accumulated_exchange_delivery_fee_for_customer', '0.0000')::numeric(19,4)
                        + coalesce(sub_q_sku.accumulated_delivery_fee
                        -> 'accumulated_refund_delivery_fee_for_channel_owner', '0.0000')::numeric(19,4)
                        + coalesce(sub_q_sku.accumulated_delivery_fee
                        -> 'accumulated_refund_delivery_fee_for_customer', '0.0000')::numeric(19,4)
                    ) as extra_delivery_fee
            from {delivery_skus.name} as sub_q_sku
            join {delivery_products.name} sub_q_product on sub_q_product.id = sub_q_sku.delivery_product_id
            group by sub_q_product.delivery_group_id
    ) sku_aggr ON sku_aggr.pgd_id = group_delivery.id
    where group_delivery.disbursement_status is not null
    """,
)

trx_v_delivery_product_sku_for_shipping_disbursement = generate_ddl(
    name="trx_v_delivery_product_sku_for_shipping_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        sku.id,
        product.id AS product_id,
        sku.id AS sku_id,
        product.title AS product_name,
        sku.title AS sku_name,
        product.is_vat,
        product.product_class,
        sku.status AS sku_status,
        product.supplier_name,
        product.seller_name,
        (
            coalesce(sku.accumulated_delivery_fee
            -> 'accumulated_exchange_delivery_fee_for_channel_owner', '0.0000')::numeric(19,4)
            + coalesce(sku.accumulated_delivery_fee
            -> 'accumulated_exchange_delivery_fee_for_customer', '0.0000')::numeric(19,4)
            + coalesce(sku.accumulated_delivery_fee
            -> 'accumulated_refund_delivery_fee_for_channel_owner', '0.0000')::numeric(19,4)
            + coalesce(sku.accumulated_delivery_fee
            -> 'accumulated_refund_delivery_fee_for_customer', '0.0000')::numeric(19,4)
        ) AS extra_delivery_fee,
        sku.purchased_finalized_date,
        sku.update_dt,
        sku.timesale_applied,
        product.delivery_pricing_method,
        product.delivery_pricing_unit,
        sku.delivery_group_id,
        sku.channel_portal_id,
        sku.supplier_portal_id,
        sku.seller_portal_id
    FROM {delivery_skus.name} AS sku
        JOIN {delivery_products.name} product ON  product.id = sku.delivery_product_id
    """,
)

trx_v_delivery_point_disbursement = generate_ddl(
    name="trx_v_delivery_point_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        pu.id as point_unit_id,
        pu.create_dt,
        pu.update_dt,
        pu.confirm_date,
        pu.channel_name,
        pu.country,
        pu.point_provider_name,
        pu.init_point_amount,
        pu.curr_point_amount,
        pu.conversion_ratio * pu.curr_point_amount as curr_point_currency_amount,
        o.id as delivery_order_id,
        pu.delivery_sku_id,
        pu.delivery_product_id,
        pu.status as point_status,
        pu.external_user_id,
        pu.channel_id,
        o.channel_portal_id
    FROM {delivery_point_units.name} AS pu
        JOIN {delivery_orders.name} AS o ON pu.delivery_transaction_id = o.delivery_transaction_id
    """,
)

trx_v_delivery_cancel_point_disbursement = generate_ddl(
    name="trx_v_delivery_cancel_point_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        pr.id as payment_refund_id,
        pu.id as point_unit_id,
        pu.create_dt,
        pr.create_dt as cancel_dt,
        pu.channel_name,
        pu.country,
        pu.point_provider_name,
        pu.init_point_amount,
        pr.point_amount_for_refund as refund_point_amount,
        pu.conversion_ratio * pr.point_amount_for_refund as refund_point_currency_amount,
        o.id as delivery_order_id,
        pu.delivery_product_id,
        pu.delivery_sku_id,
        pu.external_user_id,
        pu.channel_id,
        o.channel_portal_id
    FROM {delivery_payment_refunds.name} AS pr
        JOIN {delivery_point_units.name} AS pu ON pr.point_unit_id = pu.id
        JOIN {delivery_orders.name} AS o ON pu.delivery_transaction_id = o.delivery_transaction_id
    WHERE pr.point_unit_id IS NOT NULL
    """,
)

trx_v_excel_point_disbursement = generate_ddl(
    name="trx_v_excel_point_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        pu.create_dt,
        pu.channel_name,
        pu.point_provider_name,
        pu.id as point_unit_id,
        o.id as delivery_order_id,
        pu.delivery_product_id,
        pu.delivery_sku_id,
        sku.product_title,
        sku.title,
        sku.quantity,
        sku.status as sku_status,
        sku.sell_price * sku.quantity as sku_pv_amount,
        payment.init_pg_amount + payment.init_point_amount + payment.init_coupon_amount
        as transaction_init_paid_amount,
        pu.init_point_amount,
        pu.curr_point_amount,
        pu.conversion_ratio * pu.curr_point_amount as curr_point_currency_amount,
        pu.status as point_status,
        pu.confirm_date,
        pu.update_dt,
        pu.external_user_id,
        o.channel_portal_id
    FROM {delivery_point_units.name} AS pu
        LEFT JOIN {delivery_skus.name} sku ON pu.delivery_sku_id = sku.id
        JOIN {delivery_payments.name} payment ON pu.delivery_payment_id = payment.id
        JOIN {delivery_orders.name} o ON payment.delivery_transaction_id = o.delivery_transaction_id
    """,
)

trx_v_excel_cancel_point_disbursement = generate_ddl(
    name="trx_v_excel_cancel_point_disbursement",
    object_type="view",
    stmt=f"""
    SELECT
        pr.id as payment_refund_id,
        pu.create_dt,
        pr.create_dt as cancel_dt,
        pu.channel_name,
        pu.point_provider_name,
        pu.id as point_unit_id,
        o.id as delivery_order_id,
        pu.delivery_product_id,
        pu.delivery_sku_id,
        sku.product_title,
        sku.title,
        sku.quantity,
        sku.sell_price * sku.quantity as sku_pv_amount,
        sku.status as sku_status,
        payment.init_pg_amount + payment.init_point_amount + payment.init_coupon_amount
        as transaction_init_paid_amount,
        pu.init_point_amount,
        pr.point_amount_for_refund as refund_point_amount,
        pu.conversion_ratio * pr.point_amount_for_refund as refund_point_currency_amount,
        pu.status as point_status,
        pu.external_user_id,
        o.channel_portal_id
    FROM {delivery_payment_refunds.name} AS pr
        JOIN {delivery_point_units.name} AS pu ON pr.point_unit_id = pu.id
        JOIN {delivery_payments.name} payment ON pu.delivery_payment_id = payment.id
        JOIN {delivery_orders.name} o ON pu.delivery_transaction_id = o.delivery_transaction_id
        LEFT JOIN {delivery_skus.name} sku ON pu.delivery_sku_id = sku.id
    WHERE pr.point_unit_id IS NOT NULL
    """,
)

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
