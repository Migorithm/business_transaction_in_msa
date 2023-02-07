import inspect

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Column,
    FetchedValue,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import registry, relationship

from app.domain import base, delivery

metadata = MetaData()
mapper_registry = registry(metadata=metadata)

NUMERIC = Numeric(19, 4)

delivery_transactions = Table(
    "cvm_transaction_delivery_transaction",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("currency", String),
    Column("sender_name", String(length=32), nullable=True),
    Column("sender_phone", String(length=32), nullable=True),
    Column("sender_email", String(length=50), nullable=True),
    Column("delivery_note", String(length=256), nullable=True),
    Column("receiver_name", String(length=32), nullable=True),
    Column("receiver_phones", String(length=20), nullable=True),
    Column("receiver_address", String(length=256), nullable=True),
    Column("region_id", Integer),
    Column("postal_code", String(length=10), nullable=True),
    # Init data
    Column("user_id", String(length=50)),
    Column("status", String(length=50)),
    Column("paid_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("unsigned_secret_key", String(length=64)),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),  # system column
)

delivery_orders = Table(
    "cvm_transaction_delivery_order",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True, index=True),
    Column(
        "delivery_transaction_id",
        ForeignKey(delivery_transactions.name + ".id", ondelete="cascade"),
        nullable=False,
        index=True,
    ),
    # Meta Info (extended from v1)
    Column("country", String),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    # transaction info
    Column("settlement_frequency", Integer, default=1),
    # Init data
    Column("user_id", String(length=50)),
    Column("status", String(length=50)),
    Column("currency", String(length=50)),
    Column(
        "init_delivery_order_pv_amount",
        NUMERIC,
        CheckConstraint("curr_delivery_order_pv_amount>=0"),
        nullable=False,
        server_default="0",
    ),
    Column(
        "init_delivery_order_delivery_fee",
        NUMERIC,
        CheckConstraint("init_delivery_order_delivery_fee>=0"),
        nullable=False,
        server_default="0",
    ),
    Column(
        "curr_delivery_order_pv_amount",
        NUMERIC,
        CheckConstraint("curr_delivery_order_pv_amount>=0"),
        server_default="0",
    ),
    Column(
        "curr_delivery_order_delivery_fee",
        NUMERIC,
        CheckConstraint("curr_delivery_order_delivery_fee>=0"),
        server_default="0",
    ),
    Column("paid_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),  # system column
)


delivery_payment_logs = Table(
    "cvm_transaction_delivery_payment_log",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("delivery_transaction_id", String),
    Column("log", postgresql.JSONB),
    Column("log_type", String),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


delivery_groups = Table(
    "cvm_transaction_delivery_group",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    # Meta Info
    Column("country", String),
    Column("delivery_order_id", String),
    Column("delivery_transaction_id", String, index=True),
    #
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    # Init data
    Column("supplier_delivery_group_id", String),
    Column("supplier_delivery_group_name", String),
    Column("supplier_portal_id", String),
    Column("supplier_name", String),
    Column("calculation_method", String(8), default="max"),
    Column("region_id", Integer, default=1),
    Column("region_division_level", Integer, nullable=True),
    Column("division2_fee", Integer, nullable=True),
    Column("division3_jeju_fee", Integer, nullable=True),
    Column("division3_outside_jeju_fee", Integer, nullable=True),
    Column("is_additional_pricing_set", Boolean, nullable=True),
    Column(
        "loss_fee",
        NUMERIC,
        CheckConstraint("loss_fee>=0"),
        nullable=False,
        server_default="0",
    ),
    Column("init_calculated_group_delivery_fee", NUMERIC, CheckConstraint("init_calculated_group_delivery_fee>=0")),
    Column("init_region_additional_delivery_fee", NUMERIC, CheckConstraint("init_region_additional_delivery_fee>=0")),
    Column("init_group_delivery_discount", NUMERIC, CheckConstraint("init_group_delivery_discount>=0")),
    # Application Attribute
    Column("processing_finalized_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("curr_calculated_group_delivery_fee", NUMERIC, CheckConstraint("curr_calculated_group_delivery_fee>=0")),
    Column("curr_region_additional_delivery_fee", NUMERIC, CheckConstraint("curr_region_additional_delivery_fee>=0")),
    Column("curr_group_delivery_discount", NUMERIC, CheckConstraint("curr_group_delivery_discount>=0")),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


delivery_products = Table(
    "cvm_transaction_delivery_product",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    # Meta Info
    Column("country", String),
    Column("delivery_transaction_id", String, index=True),
    Column(
        "delivery_group_id",
        ForeignKey(delivery_groups.name + ".id", ondelete="cascade"),
        nullable=False,
        index=True,
    ),
    Column("delivery_order_id", String),
    #
    Column(
        "create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now(), nullable=False
    ),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    # Init data
    Column("sellable_product_id", String(length=50), nullable=False),
    Column("sellable_product_sn", String(length=50), nullable=False),
    Column("supplier_portal_id", String(length=50), nullable=False),
    Column("is_vat", Boolean),
    Column("master_product_id", String(length=50), nullable=False),
    Column("master_product_sn", String(length=50), nullable=False),
    Column("title", String(length=250), server_default="", nullable=False),
    Column("images", ARRAY(String), server_default="{}", nullable=False),
    Column("init_calculated_product_delivery_fee", NUMERIC, CheckConstraint("init_calculated_product_delivery_fee>=0")),
    Column("supplier_name", String),
    # Delivery_info
    Column("delivery_info", postgresql.JSONB, default=dict, nullable=False),
    Column(
        "base_delivery_fee",
        NUMERIC,
        CheckConstraint("base_delivery_fee>=0"),
        nullable=False,
        default=0,
        server_default="0",
    ),
    Column(
        "exchange_delivery_fee", NUMERIC, CheckConstraint("exchange_delivery_fee>=0"), default=0, server_default="0"
    ),
    Column("refund_delivery_fee", NUMERIC, CheckConstraint("refund_delivery_fee>=0"), default=0, server_default="0"),
    Column(
        "refund_delivery_fee_if_free_delivery",
        NUMERIC,
        CheckConstraint("refund_delivery_fee_if_free_delivery>=0"),
        default=0,
        server_default="0",
    ),
    Column("delivery_pricing_unit", String),
    Column("delivery_pricing_method", String, nullable=True),
    Column("charge_standard", NUMERIC, nullable=True, server_default="0"),
    Column("product_class", String(length=50), nullable=False),
    Column("sku_count", Integer, default=1, nullable=False),
    Column("number_of_skus_to_consider", Integer, default=0, server_default="0"),
    Column("number_of_quantity_to_consider", Integer, default=0, server_default="0"),
    Column("product_pv_amount", NUMERIC, server_default="0"),
    Column("curr_calculated_product_delivery_fee", NUMERIC, server_default="0"),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


delivery_skus = Table(
    "cvm_transaction_delivery_sku",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    #
    Column("delivery_order_id", ForeignKey(delivery_orders.name + ".id", ondelete="cascade"), index=True),
    Column("delivery_transaction_id", String, index=True),
    Column("delivery_product_id", ForeignKey(delivery_products.name + ".id", ondelete="cascade")),
    Column(
        "delivery_group_id",
        String(length=36),
        nullable=True,
    ),
    # Meta Info
    Column("user_id", String(length=50)),
    Column("country", String),
    Column("supplier_portal_id", String),
    Column("supplier_name", String),
    Column("seller_portal_id", String),
    Column("product_title", String),
    #
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("sellable_sku_id", String(length=50), nullable=False),
    Column(
        "request_status_date",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    ),
    Column("master_sku_id", String(length=50), nullable=False),
    Column("title", String(length=250), server_default="", nullable=False),
    Column("image", Text, server_default="", nullable=False),
    Column("status", String(length=50), default="payment_required", nullable=False),
    Column(
        "request_status",
        String(length=50),
        nullable=False,
    ),
    Column("carrier_code", String),
    Column("carrier_number", String),
    Column("sell_price", NUMERIC, CheckConstraint("sell_price>=0"), nullable=False, server_default="0"),
    Column("sku_pv_amount", NUMERIC),
    Column("supply_price", NUMERIC, CheckConstraint("supply_price>=0"), nullable=False, server_default="0"),
    Column("cost", NUMERIC, CheckConstraint("cost>=0"), nullable=False, server_default="-1"),
    Column("product_class", String(length=50), nullable=False),
    Column("base_delivery_fee", NUMERIC, CheckConstraint("base_delivery_fee>=0"), nullable=False, server_default="0"),
    Column("timesale_applied", Boolean, nullable=True),
    Column("quantity", Integer, CheckConstraint("quantity>=0"), default=0, nullable=False),
    Column("purchased_finalized_date", postgresql.TIMESTAMP(timezone=True)),
    Column(
        "calculated_exchange_delivery_fee",
        NUMERIC,
        nullable=False,
        server_default="-1",
    ),
    Column("delivery_tracking_data", postgresql.JSONB, default="", nullable=True),
    Column(
        "refund_delivery_fee_method",
        String(length=50),
        nullable=False,
    ),
    Column(
        "exchange_delivery_fee_method",
        String(length=50),
        nullable=False,
    ),
    Column("accumulated_delivery_fee", postgresql.JSONB, default=dict, server_default="{}", nullable=True),
    Column("unsigned_secret_key", String(64)),
    Column("options", ARRAY(postgresql.JSONB), default=list),
    Column("delivery_tracking_id", String, nullable=True),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)
delivery_sku_logs = Table(
    "cvm_transaction_delivery_sku_log",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    # Meta Info
    Column("supplier_portal_id", String(length=50)),
    Column("delivery_transaction_id", String, index=True),
    Column("delivery_order_id", String),
    Column("delivery_sku_id", ForeignKey(delivery_skus.name + ".id", ondelete="cascade"), index=True),
    Column("status", String(length=50), nullable=False, index=True),
    #
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    # Init data
    Column("user_id", String(length=50)),  # market place user id, can be same as initiator_id, can be not
    Column("initiator_id", String(length=50), nullable=False),
    Column("user_notes", postgresql.JSONB, default=dict),
    Column("supplier_notes", postgresql.JSONB, default=dict),
    Column("initiator_name", String),
    Column("initiator_type", String(length=50), nullable=False),
    Column("initiator_info", postgresql.JSONB, default=dict),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


delivery_payments = Table(
    "cvm_transaction_delivery_payments",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True),
    Column("country", String),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("delivery_transaction_id", ForeignKey(delivery_transactions.name + ".id", ondelete="cascade"), index=True),
    Column("outstandings", Text),
    Column("init_pg_amount", NUMERIC, server_default="0"),
    Column("init_point_amount", NUMERIC, server_default="0"),
    Column("init_coupon_amount", NUMERIC, server_default="0"),
    Column("curr_pg_amount", NUMERIC, server_default="0"),
    Column("curr_pg_refund_amount", NUMERIC, server_default="0"),
    Column("curr_point_amount", NUMERIC, server_default="0"),
    Column("curr_point_refund_amount", NUMERIC, server_default="0"),
    Column("curr_coupon_amount", NUMERIC, server_default="0"),
    Column("curr_coupon_refund_amount", NUMERIC, server_default="0"),
    Column("payment_method", postgresql.JSONB, default=dict),
    Column("payment_proceeding_result", postgresql.JSONB),
    Column("pg_setting_info", postgresql.JSONB, default=dict),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)

delivery_payment_refunds = Table(
    "cvm_transaction_delivery_payment_refunds",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True),
    Column("point_unit_id", String(32), nullable=True),
    Column("delivery_payment_id", ForeignKey(delivery_payments.name + ".id", ondelete="cascade"), index=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column("delivery_transaction_id", String(32)),
    Column("refund_context_sku_id", String, nullable=True),
    Column("delivery_sku_id", String, nullable=True),
    Column("point_amount_for_refund", NUMERIC, CheckConstraint("point_amount_for_refund>=0"), server_default="0"),
    Column("pg_amount_for_refund", NUMERIC, CheckConstraint("pg_amount_for_refund>=0"), server_default="0"),
    Column("coupon_amount_for_refund", NUMERIC, CheckConstraint("coupon_amount_for_refund>=0"), server_default="0"),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)

delivery_point_units = Table(
    "cvm_transaction_delivery_point_unit",
    mapper_registry.metadata,
    Column("point_provider_name", String),
    Column("point_provider_code", String),
    Column("delivery_payment_id", ForeignKey(delivery_payments.name + ".id", ondelete="cascade"), index=True),
    Column("id", String(length=36), primary_key=True),
    Column("user_id", String, index=True),
    Column("type", String),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("confirm_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("channel_id", String),
    Column("country", String),
    Column("product_title", String),
    Column("priority", Integer, default=1),
    Column("init_point_amount", NUMERIC, CheckConstraint("init_point_amount>=0")),
    Column("curr_point_amount", NUMERIC, CheckConstraint("curr_point_amount>=0")),
    Column("refund_amount", NUMERIC, CheckConstraint("refund_amount>=0")),
    Column("conversion_ratio", NUMERIC),
    Column("delivery_sku_id", String, nullable=True),
    Column("delivery_product_id", String, nullable=True),
    Column("delivery_group_id", String, nullable=True),
    Column("delivery_transaction_id", String, index=True),
    Column("status", String, default="created"),
    Column("external_user_id", String, default=""),
    Column("point_unit_type", String, nullable=True),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


delivery_trackings = Table(
    "cvm_transaction_delivery_tracking",
    mapper_registry.metadata,
    Column("id", String, primary_key=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column(
        "update_dt",
        postgresql.TIMESTAMP(timezone=True),
        default=func.now(),
        onupdate=func.current_timestamp(),
        server_default=func.now(),
    ),
    Column("carrier_code", String),
    Column("carrier_number", String, index=True),
    Column("level", Integer),
    Column("tracking_details", ARRAY(postgresql.JSONB), server_default="{}", nullable=False),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


def extract_models(module):
    for _, class_ in inspect.getmembers(module, lambda o: isinstance(o, type)):
        if issubclass(class_, base.Base) and class_ != base.Base:
            yield class_
        if issubclass(class_, base.PointBase) and class_ != base.PointBase:
            yield class_


def _get_set_hybrid_properties(models):
    for model in models:
        for method_name, _ in inspect.getmembers(model, lambda o: isinstance(o, property)):
            attr = getattr(model, method_name)
            get_ = hybrid_property(attr.fget)
            set_ = get_.setter(attr.fset) if attr.fset else None
            setattr(model, method_name, get_)
            if set_:
                setattr(model, method_name, set_)


def start_mappers():
    _get_set_hybrid_properties(extract_models(delivery))

    mapper_registry.map_imperatively(
        delivery.DeliveryTracking,
        delivery_trackings,
        properties={
            "delivery_skus": relationship(
                delivery.DeliverySku,
                back_populates="delivery_tracking",
                primaryjoin="foreign(delivery.DeliverySku.delivery_tracking_id) == delivery.DeliveryTracking.id",
                collection_class=set,
            )
        },
        eager_defaults=True,
        version_id_col=delivery_trackings.c.xmin,
        version_id_generator=False,
    )

    mapper_registry.map_imperatively(
        delivery.DeliveryPaymentLog,
        delivery_payment_logs,
        # New
        properties={
            "delivery_transaction": relationship(
                delivery.DeliveryTransaction,
                back_populates="delivery_payment_logs",
                primaryjoin="foreign(delivery.DeliveryPaymentLog.delivery_transaction_id)"
                " == delivery.DeliveryTransaction.id",
                uselist=False,
                innerjoin=True,
                # primaryjoin=f"{payment_logs.name}.c.delivery_order_id == {delivery_orders.name}.c.id"
            )
        },
        eager_defaults=True,
        version_id_col=delivery_payment_logs.c.xmin,
        version_id_generator=False,
    )

    mapper_registry.map_imperatively(
        delivery.DeliverySkuLog,
        delivery_sku_logs,
        properties={
            "delivery_sku": relationship(
                delivery.DeliverySku,
                back_populates="delivery_sku_logs",
                innerjoin=True,
                uselist=False,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_sku_logs.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryPointUnit,
        delivery_point_units,
        properties={
            "delivery_payment": relationship(delivery.DeliveryPayment, back_populates="delivery_point_units"),
        },
        eager_defaults=True,
        version_id_col=delivery_point_units.c.xmin,
        version_id_generator=False,
    )

    mapper_registry.map_imperatively(
        delivery.DeliverySku,
        delivery_skus,
        properties={
            "delivery_order": relationship(
                delivery.DeliveryOrder,
                back_populates="delivery_skus",
                innerjoin=True,
                uselist=False,
            ),
            "delivery_product": relationship(
                delivery.DeliveryProduct,
                back_populates="delivery_skus",
                innerjoin=True,
                uselist=False,
            ),
            "delivery_sku_logs": relationship(
                delivery.DeliverySkuLog,
                back_populates="delivery_sku",
                cascade="all, delete-orphan",
                collection_class=list,
            ),
            "delivery_tracking": relationship(
                delivery.DeliveryTracking,
                back_populates="delivery_skus",
                primaryjoin="foreign(delivery.DeliverySku.delivery_tracking_id) == delivery.DeliveryTracking.id",
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_skus.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryProduct,
        delivery_products,
        properties={
            "delivery_skus": relationship(
                delivery.DeliverySku,
                back_populates="delivery_product",
                cascade="all, delete-orphan",
                collection_class=set,
            ),
            "delivery_order": relationship(
                delivery.DeliveryOrder,
                # secondary?
                secondary=delivery_skus,
                primaryjoin=f"{delivery_products.name}.c.id== {delivery_skus.name}.c.delivery_product_id",
                secondaryjoin=f"{delivery_skus.name}.c.delivery_order_id == {delivery_orders.name}.c.id",
                back_populates="delivery_products",
                uselist=False,
                viewonly=True,
                innerjoin=True,
            ),
            "delivery_group": relationship(
                delivery.DeliveryGroup,
                back_populates="delivery_products",
                innerjoin=True,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_products.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryGroup,
        delivery_groups,
        properties={
            "delivery_products": relationship(
                delivery.DeliveryProduct,
                back_populates="delivery_group",
                cascade="all, delete-orphan",
                innerjoin=True,
                collection_class=set,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_groups.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryOrder,
        delivery_orders,
        properties={
            "delivery_products": relationship(
                delivery.DeliveryProduct,
                # secondary?
                secondary=delivery_skus,
                primaryjoin=f"{delivery_orders.name}.c.id == {delivery_skus.name}.c.delivery_order_id",
                secondaryjoin=f"{delivery_skus.name}.c.delivery_product_id == {delivery_products.name}.c.id",
                back_populates="delivery_order",
                innerjoin=True,
                viewonly=True,
                collection_class=set,
            ),
            "delivery_skus": relationship(
                delivery.DeliverySku,
                back_populates="delivery_order",
                collection_class=set,
                innerjoin=True,
            ),
            "delivery_transaction": relationship(
                delivery.DeliveryTransaction,
                back_populates="delivery_orders",
                innerjoin=True,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_orders.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryTransaction,
        delivery_transactions,
        properties={
            "delivery_orders": relationship(
                delivery.DeliveryOrder, back_populates="delivery_transaction", collection_class=set
            ),
            "delivery_payment": relationship(
                delivery.DeliveryPayment, back_populates="delivery_transaction", uselist=False, innerjoin=True
            ),
            "delivery_payment_logs": relationship(
                delivery.DeliveryPaymentLog,
                back_populates="delivery_transaction",
                primaryjoin="foreign(delivery.DeliveryPaymentLog.delivery_transaction_id)"
                " == delivery.DeliveryTransaction.id",
                collection_class=set,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_transactions.c.xmin,
        version_id_generator=False,
    )
    mapper_registry.map_imperatively(
        delivery.DeliveryPaymentRefund,
        delivery_payment_refunds,
        properties={
            "delivery_payment": relationship(
                delivery.DeliveryPayment,
                back_populates="delivery_payment_refunds",
            )
        },
        eager_defaults=True,
        version_id_col=delivery_payment_refunds.c.xmin,
        version_id_generator=False,
    ),
    mapper_registry.map_imperatively(
        delivery.DeliveryPayment,
        delivery_payments,
        properties={
            "delivery_point_units": relationship(
                delivery.DeliveryPointUnit,
                back_populates="delivery_payment",
                uselist=True,
                collection_class=set,
            ),
            "delivery_transaction": relationship(
                delivery.DeliveryTransaction,
                back_populates="delivery_payment",
                innerjoin=True,
                uselist=False,
            ),
            "delivery_payment_refunds": relationship(
                delivery.DeliveryPaymentRefund,
                back_populates="delivery_payment",
                collection_class=list,
                order_by=delivery_payment_refunds.c.create_dt,
            ),
        },
        eager_defaults=True,
        version_id_col=delivery_payments.c.xmin,
        version_id_generator=False,
    )
