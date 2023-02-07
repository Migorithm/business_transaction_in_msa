from __future__ import annotations

import copy
import logging
import secrets
import string
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from functools import cache
from typing import Protocol

from pydantic import BaseModel

from app.domain import commands
from app.domain import events as domain_events
from app.domain.base import BaseEnums, Order, Payment, PaymentLog, PaymentRefund, PointUnit, Sku, SkuLog, Transaction
from app.utils import time_util

logger = logging.getLogger(__name__)


class Protocols:
    class PtIn(Protocol):
        point_provider_name: str
        point_provider_code: str
        external_user_id: str | None
        requested_point_amount: Decimal
        type: str
        priority: int | None
        sku_id: str | None
        conversion_ratio: Decimal = Decimal("1")


class Schemas:
    class PaymentOutstandings(BaseModel):
        pg_amount: Decimal
        point_units: list[Protocols.PtIn] = []

        class Config:
            json_encoders = {Decimal: lambda v: int(v)}


def sn_alphanum(length: int = 10) -> str:
    """
    generate sn with combination of
    Uppercase Alphabet and numbers 1 - 9
    """
    return "".join(secrets.choice(string.ascii_uppercase + string.digits[1:]) for _ in range(length))


@dataclass(eq=False)
class ServiceTransaction(Transaction):
    sender_name: str
    sender_phone: str
    sender_email: str
    country: str
    currency: str
    user_id: str

    def __post_init__(self):
        self.payment = ServicePayment(
            id=ServicePayment.sn_payment(),
            service_transaction_id=self.id,
            country=self.country,
            service_transaction=self,
        )
        for o in self.orders:
            o.transaction_id = self.id
            o.user_id = self.user_id
            for s in o.skus:
                s.transaction_id = self.id
                s.user_id = self.user_id

    paid_date: datetime = field(init=False)

    service_orders: set[ServiceOrder]

    service_payment: ServicePayment = field(init=False)
    service_payment_logs: set[ServicePaymentLog] = field(init=False)
    status: BaseEnums.TransactionStatus = BaseEnums.TransactionStatus.PAYMENT_REQUIRED
    type: str = "service"
    unsigned_secret_key: str = ""
    xmin: int = field(init=False, repr=False)
    events: deque = deque()

    @property
    def orders(self):
        return self.service_orders

    def get_order(self, ref) -> ServiceOrder | None:
        return next((o for o in self.orders if o.id == ref), None)

    @property
    def skus(self):
        return {sku for order in self.orders for sku in order.skus}

    @property
    def payment(self):
        return self.service_payment

    @payment.setter
    def payment(self, payment):
        self.service_payment = payment

    @property
    def payment_logs(self):
        return self.service_payment_logs

    @property
    def payment_refunds(self):
        return self.payment.payment_refunds

    @property
    def point_units(self):
        return self.payment.point_units

    @property
    def curr_transaction_pv_amount(self):
        return sum(o.curr_service_order_pv_amount for o in self.orders) or Decimal("0")

    @property
    def init_transaction_pv_amount(self):
        return sum(o.init_service_order_pv_amount for o in self.orders)

    @classmethod
    def _create_(cls, *, orders: set[ServiceOrder], **kwargs) -> ServiceTransaction:
        assert kwargs.get("shipping_info")
        service_order_info = kwargs["shipping_info"]

        service_transaction_data = dict(
            id=cls.sn_transaction(),
            service_orders=orders,
        )
        service_transaction_data["currency"] = kwargs.get("currency", "KRW")
        service_transaction_data["country"] = kwargs.get("country", "")
        service_transaction_data["user_id"] = kwargs.get("user_id", "anonymous")

        service_transaction_data |= service_order_info.dict(exclude_none=True)
        service_transaction = cls.from_kwargs(**service_transaction_data)
        return service_transaction

    @classmethod
    def _create(
        cls,
        msg: commands.CreateOrder,
    ) -> tuple:
        order, *sub_obj = ServiceOrder.create(msg=msg)
        _ = cls._create_(
            orders={order},
            shipping_info=msg.shipping_info,
            user_id=msg.marketplace_user_data.user_id,
        )
        return order, *sub_obj

    @staticmethod
    def sn_transaction(*args, **kwargs):
        return "ST-" + sn_alphanum(length=12)

    def update_status(self, *, context: BaseEnums.TransactionStatus, **kwargs):
        if context == BaseEnums.TransactionStatus.PAID:
            _paid_date = time_util.current_time()
            self.status = context
            self.paid_date = _paid_date
            for o in self.orders:
                o.paid_date = _paid_date
                # TODO Status Set
        else:
            self.status = context

    def change_sku_status_in_bulk(
        self,
        msg: domain_events.OrderCompleted | domain_events.PGPaymentFailed | domain_events.PointUseRequestFailed,
    ):
        on_payment = self.status == BaseEnums.TransactionStatus.PAID
        status = msg.sku_status_to_change
        for sku in self.skus:
            sku.update_status(context=status)
            if on_payment:
                sku.request_status_date = time_util.current_time()
                sku.request_status = status
            sku.create_log(
                user_id=self.user_id,
                username=msg.marketplace_user_data.nickname,
                initiator_type=BaseEnums.InitiatorType.SYSTEM,
            )

    def create_payment_log_on_create(self, **kwargs):
        if transaction_id := kwargs.get("transaction_id"):
            kwargs["service_transaction_id"] = transaction_id
            del kwargs["transaction_id"]
        payment_log = ServicePaymentLog(id=ServicePaymentLog.sn_payment_log(), **kwargs)
        self.payment_logs.add(payment_log)

    def create_payment_log_on_cancel(self, pg_response: dict, **kwargs):
        payment = self.payment
        pg_type = payment.pg_setting_info["pg_type"]
        if pg_type == "smartro" and pg_response["ResultCode"] not in ("2001", "2211"):
            log_type = "cancellation_failed"
        elif pg_type == "kginicis" and pg_response.get("resultCode", "") not in ("00", "0000"):
            log_type = "cancellation_failed"
        else:
            log_type = "cancellation_succeeded"
        self.payment_logs.add(
            ServicePaymentLog.from_kwargs(
                id=ServicePaymentLog.sn_payment_log(),
                log_type=log_type,
                log=pg_response,
            )
        )

    # TODO
    def cancel_claim_out(self, refund_amount: Decimal, note: str) -> dict:  # type: ignore
        ...

    # TODO
    def get_anonymous_access_key(self):
        ...


@dataclass(eq=False)
class ServiceOrder(Order):
    # Mappings

    country: str
    settlement_frequency: int
    user_id: str
    status: str
    currency: str
    service_skus: set[ServiceSku] = field(init=False)
    # service_products: set[ServiceProduct] = field(init=False)
    service_transaction_id: str = field(init=False)
    service_transaction: ServiceTransaction = field(init=False)
    paid_date: datetime | None = field(default=None)
    xmin: int = field(init=False, repr=False)
    events: deque = deque()

    init_service_order_pv_amount: Decimal = field(init=False)
    curr_service_order_pv_amount: Decimal = field(init=False)

    @property
    def payment(self):
        return self.transaction.payment

    @property
    def skus(self) -> set[ServiceSku]:
        return self.service_skus

    @skus.setter
    def skus(self, skus):
        self.service_skus = skus

    @property
    def transaction(self):
        return self.service_transaction

    @transaction.setter
    def transaction(self, transaction):
        self.service_transaction = transaction

    @property
    def transaction_id(self):
        return self.service_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.service_transaction_id = transaction_id

    @property
    def curr_order_pv_amount(self):
        return self.curr_service_order_pv_amount

    @curr_order_pv_amount.setter
    def curr_order_pv_amount(self, curr_order_pv_amount):
        self.curr_service_order_pv_amount = curr_order_pv_amount

    @property
    def init_order_pv_amount(self):
        return self.init_service_order_pv_amount

    @staticmethod
    def sn_order(*args, **kwargs):
        return "SO-" + sn_alphanum(length=12)

    @classmethod
    def _create(cls, msg: commands.CreateOrder, **kwargs) -> tuple[ServiceOrder, set[ServiceSku]]:
        service_skus = ServiceSku.create(msg)
        service_order = cls.from_kwargs(
            id=cls.sn_order(),
            service_skus=service_skus,
            currency=msg.currency,
            status="unconfirmed",  # TODO Need to set
            country=msg.channel_info.country,
            user_id=msg.marketplace_user_data.user_id,
            settlement_frequency=msg.channel_info.settlement_frequency,
        )
        service_order.calculate_fees()

        return service_order, service_skus

    def calculate_fees(self) -> None:
        self.curr_order_pv_amount = sum(
            (sku.quantity * sku.sell_price) for sku in self.skus if sku not in sku.not_countable_statuses
        )

    def set_payment_outstandings(self, points: list[Protocols.PtIn]):
        return self.payment.set_payment_outstandings(points=points)

    def precalculate_on_checkout(*args, **kwargs):  # type: ignore
        ...

    def dict(*args, **kwargs) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class ServicePaymentLog(PaymentLog):
    id: str
    service_transaction: ServiceTransaction = field(init=False)
    log_type: str = ""
    log: dict = field(default_factory=dict)
    service_transaction_id: str = field(default="", repr=False)
    xmin: int = field(init=False, repr=False)

    @staticmethod
    def sn_payment_log(*args, **kwargs):
        return "SPL-" + sn_alphanum(length=11)


@dataclass(eq=False)
class ServiceSku(Sku):
    class Status(str, Enum):
        PAYMENT_FAIL_ERROR = "payment_fail_error"
        PAYMENT_FAIL_VALIDATION = "payment_fail_validation"
        PAYMENT_FAIL_POINT_ERROR = "payment_fail_point_error"
        UNSELECTED_IN_CART = "unselected"
        TO_BE_ISSUED = "to_be_issued"
        RECEIVED = "received"
        USED = "used"
        USE_CONFIRMED = "use_confirmed"
        ISSUE_CANCELED = "issue_canceled"
        EXPIRED = "expired"
        EXPIRE_CONFIRMED = "expired_confirmed"  # return 90% worth of money

    service_order: ServiceOrder = field(init=False)
    service_sku_logs: list[ServiceSkuLog] = field(init=False)
    service_order_id: str = field(init=False)
    service_transaction_id: str = field(init=False)

    pin_number: str | None = field(init=False)
    product_title: str = field(init=False)
    title: str = field(init=False)
    status: ServiceSku.Status = field(init=False)
    country: str = field(init=False)
    user_id: str = field(init=False)
    sellable_sku_id: str
    image: str
    request_status: str = field(init=False)
    request_status_date: datetime = field(init=False)
    sell_price: Decimal
    sku_pv_amount: Decimal = field(init=False)

    product_class: BaseEnums.ProductClass
    timesale_applied: bool
    quantity: int
    purchased_finalized_date: datetime = field(init=False)

    expiration_date: datetime = field(init=False)
    is_vat: bool
    options: list = field(default_factory=list)
    unsigned_secret_key: str = ""
    xmin: int = field(init=False, repr=False)

    @property
    def transaction_id(self):
        return self.service_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.service_transaction_id = transaction_id

    @property
    def sku_logs(self):
        return self.service_sku_logs

    @sku_logs.setter
    def sku_logs(self, sku_logs):
        self.service_sku_logs = sku_logs

    @property
    def order(self):
        return self.service_order

    @property
    def order_id(self):
        return self.service_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.service_order_id = order_id

    @property
    @cache
    def not_countable_statuses(self):
        return (
            ServiceSku.Status.UNSELECTED_IN_CART,
            ServiceSku.Status.ISSUE_CANCELED,
            ServiceSku.Status.EXPIRE_CONFIRMED,
        )

    @staticmethod
    def sn_sku(*args, **kwargs):
        return "SS-" + sn_alphanum(length=12)  # ServiceSku

    @classmethod
    def _create(cls, msg: commands.CreateOrder, **kwargs):
        assert msg.service_products_to_order
        skus_to_order = msg.service_products_to_order
        sellable_sku_qty_mapper = msg.sellable_sku_qty_mapper
        skus = set()
        for sku_info in skus_to_order:
            sku_info["sellable_sku_id"] = sku_info["id"]
            for _ in range(sellable_sku_qty_mapper.get(sku_info["sellable_sku_id"], 0)):
                sku_create_data = copy.copy(sku_info)
                sku_create_data["quantity"] = 1
                sku_create_data["id"] = cls.sn_sku()
                sku = cls.from_kwargs(**sku_create_data)
                skus.add(sku)
        return skus

    def calculate_refund_price_on_partial_cancelation(self, *, refund_context):
        pass

    def update_status(self, *, context: ServiceSku.Status, **kwargs):
        self.status = context

    def create_log(self, **kwargs):
        self.sku_logs.append(ServiceSkuLog.from_kwargs(id=ServiceSkuLog.sn_sku_log(), service_sku=self, **kwargs))

    @staticmethod
    def dict(*args, **kwargs) -> dict:
        return {}


@dataclass(eq=False)
class ServiceSkuLog(SkuLog):
    service_transaction_id: str = field(init=False)
    service_order_id: str = field(init=False)
    service_sku_id: str = field(init=False)
    status: str = field(init=False)
    xmin: int = field(init=False, repr=False)

    # Post Init
    def __post_init__(self):
        assert self.sku
        sku = self.sku
        self.channel_id = sku.channel_id
        self.channel_name = sku.channel_name
        self.user_id = sku.user_id
        self.order_id = sku.order_id
        self.transaction_id = sku.transaction_id
        self.sku_id = sku.id
        self.status = sku.status

    user_id: str = field(init=False)  # market place user id, can be same as initiator_id, can be not
    service_sku: ServiceSku | None = None
    initiator_id: str = ""

    user_notes: dict = field(default_factory=dict)
    channel_admin_notes: dict = field(default_factory=dict)

    initiator_name: str = ""
    initiator_type: str = ""
    initiator_info: dict = field(default_factory=dict)

    @property
    def sku(self):
        return self.service_sku

    @sku.setter
    def sku(self, sku):
        self.service_sku = sku

    @property
    def order_id(self):
        return self.service_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.service_order_id = order_id

    @property
    def transaction_id(self):
        return self.service_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.service_transaction_id = transaction_id

    @staticmethod
    def sn_sku_log(*args, **kwargs):
        return "SSL-" + sn_alphanum(length=11)

    def dict(self):
        ...


@dataclass(eq=False)
class ServicePayment(Payment):
    # mapping
    id: str
    service_transaction: ServiceTransaction
    service_transaction_id: str

    country: str

    outstandings: str = field(init=False)

    init_pg_amount: Decimal = Decimal("0")
    init_point_amount: Decimal = Decimal("0")
    init_coupon_amount: Decimal = Decimal("0")
    curr_pg_amount: Decimal = Decimal("0")
    curr_pg_refund_amount: Decimal = Decimal("0")
    curr_point_amount: Decimal = Decimal("0")
    curr_point_refund_amount: Decimal = Decimal("0")
    curr_coupon_amount: Decimal = Decimal("0")
    curr_coupon_refund_amount: Decimal = Decimal("0")
    payment_method: dict = field(default_factory=dict)
    payment_proceeding_result: dict = field(default_factory=dict)
    pg_setting_info: dict = field(default_factory=dict)

    xmin: int = field(init=False, repr=False)
    service_point_units: set[ServicePointUnit] = field(default_factory=set)
    service_payment_refunds: list[ServicePaymentRefund] = field(default_factory=list)
    events: deque = deque()

    @property
    def transaction_id(self):
        return self.service_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.service_transaction_id = transaction_id

    @property
    def orders(self):
        return self.transaction.orders

    @property
    def payment_refunds(self):
        return self.service_payment_refunds

    @payment_refunds.setter
    def payment_refunds(self, payment_refunds):
        self.service_payment_refunds = payment_refunds

    @property
    def point_units(self):
        return self.service_point_units

    @point_units.setter
    def point_units(self, point_units):
        self.service_point_units = point_units

    @property
    def transaction(self):
        return self.service_transaction

    @transaction.setter
    def transaction(self, transaction):
        self.service_transaction = transaction

    @staticmethod
    def sn_payment(*args, **kwargs):
        return "SP-" + sn_alphanum(length=12)

    def get_payment_outstandings(self):
        if self.outstandings:
            # TODO Outbox pattern
            return Schemas.PaymentOutstandings.parse_raw(self.outstandings)
        return None

    def set_payment_outstandings(self, points: list[Protocols.PtIn]):
        pv_amount = self.transaction.curr_transaction_pv_amount
        point_amount = sum(pt.requested_point_amount for pt in points) or Decimal("0")
        pg_amount = pv_amount - point_amount
        self.outstandings = Schemas.PaymentOutstandings(point_units=points, pg_amount=pg_amount).json()

        pg_processing_required = pg_amount > 0
        point_processing_required = sum(pt.requested_point_amount for pt in points) > 0
        return pg_processing_required, point_processing_required

    def get_cancelation_outstandings(self):
        pass

    def set_partial_cancelation_outstandings(
        self,
        *,
        sku_id: str,
        point_units_to_subtract: list,
        refund_amount,
        marketplace_user_data,
        note: str,
        refund_context: str = "",
        generating_event_required: bool,
        **kwargs,
    ):
        pass

    def set_full_cancelation_outstandings(
        self, *, pg_refund_amount: Decimal, marketplace_user_data, note: str, **kwargs
    ):
        pass

    def deduct_point_units(self):
        pass

    def set_outstandings_on_point_request_fail(self, *, marketplace_user_data):
        pass

    def create_point_units(self):
        pass

    def update_point_paid_amount_on_payment(self, *, marketplace_user_data, is_cart_order: bool, **kwargs):
        pass

    def create_refund_logs(self):
        pass

    def set_confirm_date_on_transaction_point(self):
        pass

    def set_confirm_date_on_sku_point(self, *, sku: Sku):
        pass

    def process_pg_complete_order_result(
        self,
        res: str,
        cmd: commands.CompletePg,
    ):
        if res.endswith("invalid_payment_trial"):
            return None

        outstandings = self.get_payment_outstandings()
        assert outstandings

        point_processing_required = outstandings.point_units != []

        sku_status_to_change: str = ""
        event: domain_events.Message | None = None

        # FAIL Case
        if self.transaction.status == BaseEnums.TransactionStatus.FAILED:
            if res.endswith("validation_fail"):
                sku_status_to_change = ServiceSku.Status.PAYMENT_FAIL_VALIDATION.value
                logger.exception(
                    "Payment Validation Fail!: {}\nPG type:{}".format(
                        self.transaction_id, self.pg_setting_info["pg_type"]  # TODO -> locate id
                    )
                )
            else:
                sku_status_to_change = ServiceSku.Status.PAYMENT_FAIL_ERROR.value
                logger.exception(
                    "Payment Fail!: {}\nPG type:{}".format(self.transaction_id, self.pg_setting_info["pg_type"])
                )
            event = domain_events.PGPaymentFailed(
                transaction_id=self.transaction_id,
                marketplace_user_data=cmd.marketplace_user_data,
                sku_status_to_change=sku_status_to_change,
            )

        # SUCCESS Case
        elif self.transaction.status == BaseEnums.TransactionStatus.PAID:
            # Set Pg amount
            self.init_pg_amount = outstandings.pg_amount
            self.curr_pg_amount = outstandings.pg_amount

            sku_status_to_change = ServiceSku.Status.TO_BE_ISSUED.value

            event = domain_events.PGPaymentCompleted(
                transaction_id=str(self.transaction_id),
                is_cart_order=cmd.is_cart_order,
                marketplace_user_data=cmd.marketplace_user_data,
                sku_ids=[str(sku.id) for sku in self.transaction.skus],
                sku_status_to_change=sku_status_to_change,
                inventory_change_option=False,
                pg_processing_required=False,
                point_processing_required=point_processing_required,
            )
        self.transaction.events.append(event)
        return None

    @staticmethod
    def dict(*args, **kwargs):
        pass


@dataclass(eq=False)
class ServicePaymentRefund(PaymentRefund):
    service_payment: ServicePayment
    service_payment_id: str
    point_unit_id: str
    service_transaction_id: str

    service_sku_id: str
    point_amount_for_refund: Decimal
    pg_amount_for_refund: Decimal
    coupon_amount_for_refund: Decimal
    xmin: int = field(init=False, repr=False)


@dataclass(eq=False)
class ServicePointUnit(PointUnit):
    service_payment: ServicePayment
    service_payment_id: str
    point_provider_name: str
    point_provider_code: str
    user_id: str
    type: str
    confirm_date: datetime = field(init=False)

    country: str
    product_title: str
    init_point_amount: Decimal
    curr_point_amount: Decimal
    refund_amount: Decimal
    conversion_ratio: Decimal
    service_sku_id: str
    service_transaction_id: str
    status: str
    external_user_id: str
    point_unit_type: str
    priority: int = 1
    xmin: int = field(init=False, repr=False)
