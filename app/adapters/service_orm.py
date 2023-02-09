# import inspect

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

# from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import registry  # , relationship

# from app.domain import base, service

NUMERIC = Numeric(19, 4)
metadata = MetaData()
mapper_registry = registry(metadata=metadata)

service_transactions = Table(
    "cvm_transaction_service_transaction",
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
    Column("country", String),
    Column("currency", String),
    Column("sender_name", String(length=32), nullable=True),
    Column("sender_phone", String(length=32), nullable=True),
    Column("sender_email", String(length=50), nullable=True),
    # Init data
    Column("user_id", String(length=50)),
    Column("status", String(length=50)),
    Column("paid_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("unsigned_secret_key", String(length=64)),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),  # system column
)


service_orders = Table(
    "cvm_transaction_service_order",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True, index=True),
    Column(
        "service_transaction_id",
        ForeignKey(service_transactions.name + ".id", ondelete="cascade"),
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
        "init_service_order_pv_amount",
        NUMERIC,
        CheckConstraint("init_service_order_pv_amount>=0"),
        nullable=False,
        server_default="0",
    ),
    Column(
        "curr_service_order_pv_amount",
        NUMERIC,
        CheckConstraint("curr_service_order_pv_amount>=0"),
        server_default="0",
    ),
    Column("paid_date", postgresql.TIMESTAMP(timezone=True), nullable=True),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),  # system column
)


service_skus = Table(
    "cvm_transaction_service_sku",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    Column("pin_number", Text, nullable=True),
    Column(
        "expiration_date",
        postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    ),
    #
    Column("service_order_id", ForeignKey(service_orders.name + ".id", ondelete="cascade"), index=True),
    Column("service_transaction_id", String, index=True),
    # Column("service_product_id", ForeignKey(service_products.name + ".id", ondelete="cascade")),
    # Meta Info
    Column("user_id", String(length=50)),
    Column("country", String),
    Column("supplier_portal_id", String),
    Column("supplier_name", String),
    Column("seller_portal_id", String),
    Column("seller_name", String),
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
    Column("status", String(length=50), nullable=False),
    Column(
        "request_status",
        String(length=50),
        nullable=False,
    ),
    Column("sell_price", NUMERIC, CheckConstraint("sell_price>=0"), nullable=False, server_default="0"),
    Column("sku_pv_amount", NUMERIC),
    Column("supply_price", NUMERIC, CheckConstraint("supply_price>=0"), nullable=False, server_default="0"),
    Column("cost", NUMERIC, CheckConstraint("cost>=0"), nullable=False, server_default="-1"),
    Column("product_class", String(length=50), nullable=False, server_default="giftcard"),
    Column("timesale_applied", Boolean, nullable=True),
    Column("quantity", Integer, CheckConstraint("quantity>=0"), default=0, nullable=False),
    Column("purchased_finalized_date", postgresql.TIMESTAMP(timezone=True)),
    Column("unsigned_secret_key", String(64)),
    Column("options", ARRAY(postgresql.JSONB), default=list),
    # Disbursement goods field
    Column("is_vat", Boolean),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)

service_sku_logs = Table(
    "cvm_transaction_service_sku_log",
    mapper_registry.metadata,
    Column(
        "id",
        String(length=36),
        primary_key=True,
    ),
    # Meta Info
    Column("supplier_portal_id", String(length=50)),
    Column("service_transaction_id", String, index=True),
    Column("service_order_id", String),
    Column("service_sku_id", ForeignKey(service_skus.name + ".id", ondelete="cascade"), index=True),
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
    Column("channel_admin_notes", postgresql.JSONB, default=dict),
    Column("supplier_notes", postgresql.JSONB, default=dict),
    Column("initiator_name", String),
    Column("initiator_type", String(length=50), nullable=False),
    Column("initiator_info", postgresql.JSONB, default=dict),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


service_payments = Table(
    "cvm_transaction_service_payments",
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
    Column("service_transaction_id", ForeignKey(service_transactions.name + ".id", ondelete="cascade"), index=True),
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

service_payment_refunds = Table(
    "cvm_transaction_service_payment_refunds",
    mapper_registry.metadata,
    Column("id", String(length=36), primary_key=True),
    Column("point_unit_id", String(32), nullable=True),
    Column("service_payment_id", ForeignKey(service_payments.name + ".id", ondelete="cascade"), index=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column("service_transaction_id", String(32)),
    Column("service_sku_id", String, nullable=True),
    Column("point_amount_for_refund", NUMERIC, CheckConstraint("point_amount_for_refund>=0"), server_default="0"),
    Column("pg_amount_for_refund", NUMERIC, CheckConstraint("pg_amount_for_refund>=0"), server_default="0"),
    Column("coupon_amount_for_refund", NUMERIC, CheckConstraint("coupon_amount_for_refund>=0"), server_default="0"),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)

service_point_units = Table(
    "cvm_transaction_service_point_unit",
    mapper_registry.metadata,
    # From Channel
    Column("point_provider_name", String),
    Column("point_provider_code", String),
    Column("service_payment_id", ForeignKey(service_payments.name + ".id", ondelete="cascade"), index=True),
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
    Column("country", String),
    Column("product_title", String),
    Column("priority", Integer, default=1),
    Column("init_point_amount", NUMERIC, CheckConstraint("init_point_amount>=0")),
    Column("curr_point_amount", NUMERIC, CheckConstraint("curr_point_amount>=0")),
    Column("refund_amount", NUMERIC, CheckConstraint("refund_amount>=0")),
    Column("conversion_ratio", NUMERIC),
    Column("service_sku_id", String, nullable=True),
    Column("service_transaction_id", String, index=True),
    Column("status", String, default="created"),
    Column("external_user_id", String, default=""),
    Column("point_unit_type", String, nullable=True),
    Column("xmin", Integer, system=True, server_default=FetchedValue()),
)


# def extract_models(module):
#     for _, class_ in inspect.getmembers(module, lambda o: isinstance(o, type)):
#         if issubclass(class_, base.Base) and class_ != base.Base:
#             yield class_
#         if issubclass(class_, base.PointBase) and class_ != base.PointBase:
#             yield class_


# def _get_set_hybrid_properties(models):
#     for model in models:
#         for method_name, _ in inspect.getmembers(model, lambda o: isinstance(o, property)):
#             attr = getattr(model, method_name)
#             get_ = hybrid_property(attr.fget)
#             set_ = get_.setter(attr.fset) if attr.fset else None
#             setattr(model, method_name, get_)
#             if set_:
#                 setattr(model, method_name, set_)


# def start_mappers():
#     _get_set_hybrid_properties(extract_models(service))

#     mapper_registry.map_imperatively(
#         service.ServiceSkuLog,
#         service_sku_logs,
#         properties={
#             "service_sku": relationship(
#                 service.ServiceSku,
#                 back_populates="service_sku_logs",
#                 innerjoin=True,
#                 uselist=False,
#             ),
#         },
#         eager_defaults=True,
#         version_id_col=service_sku_logs.c.xmin,
#         version_id_generator=False,
#     )

#     mapper_registry.map_imperatively(
#         service.ServicePointUnit,
#         service_point_units,
#         properties={
#             "service_payment": relationship(service.ServicePayment, back_populates="service_point_units"),
#         },
#         eager_defaults=True,
#         version_id_col=service_point_units.c.xmin,
#         version_id_generator=False,
#     )

#     mapper_registry.map_imperatively(
#         service.ServiceSku,
#         service_skus,
#         properties={
#             "service_order": relationship(
#                 service.ServiceOrder,
#                 back_populates="service_skus",
#                 innerjoin=True,
#                 uselist=False,
#             ),
#             "service_sku_logs": relationship(
#                 service.ServiceSkuLog,
#                 back_populates="service_sku",
#                 cascade="all, delete-orphan",
#                 collection_class=list,
#             ),
#         },
#         eager_defaults=True,
#         version_id_col=service_skus.c.xmin,
#         version_id_generator=False,
#     )
#     mapper_registry.map_imperatively(
#         service.ServiceOrder,
#         service_orders,
#         properties={
#             "service_skus": relationship(
#                 service.ServiceSku,
#                 back_populates="service_order",
#                 collection_class=set,
#                 innerjoin=True,
#             ),
#             "service_transaction": relationship(
#                 service.ServiceTransaction,
#                 back_populates="service_orders",
#                 innerjoin=True,
#             ),
#         },
#         eager_defaults=True,
#         version_id_col=service_orders.c.xmin,
#         version_id_generator=False,
#     )

#     mapper_registry.map_imperatively(
#         service.ServiceTransaction,
#         service_transactions,
#         properties={
#             "service_orders": relationship(
#                 service.ServiceOrder, back_populates="service_transaction", collection_class=set
#             ),
#             "service_payment": relationship(
#                 service.ServicePayment, back_populates="service_transaction", uselist=False, innerjoin=True
#             ),

#         },
#         eager_defaults=True,
#         version_id_col=service_transactions.c.xmin,
#         version_id_generator=False,
#     )
#     mapper_registry.map_imperatively(
#         service.ServicePaymentRefund,
#         service_payment_refunds,
#         properties={
#             "service_payment": relationship(
#                 service.ServicePayment,
#                 back_populates="service_payment_refunds",
#             )
#         },
#         eager_defaults=True,
#         version_id_col=service_payment_refunds.c.xmin,
#         version_id_generator=False,
#     ),
#     mapper_registry.map_imperatively(
#         service.ServicePayment,
#         service_payments,
#         properties={
#             "service_point_units": relationship(
#                 service.ServicePointUnit,
#                 back_populates="service_payment",
#                 uselist=True,
#                 collection_class=set,
#             ),
#             "service_transaction": relationship(
#                 service.ServiceTransaction,
#                 back_populates="service_payment",
#                 innerjoin=True,
#                 uselist=False,
#             ),
#             "service_payment_refunds": relationship(
#                 service.ServicePaymentRefund,
#                 back_populates="service_payment",
#                 collection_class=list,
#                 order_by=service_payment_refunds.c.create_dt,
#             ),
#         },
#         eager_defaults=True,
#         version_id_col=service_payments.c.xmin,
#         version_id_generator=False,
#     )
