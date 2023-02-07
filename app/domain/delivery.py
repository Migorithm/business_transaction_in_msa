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
from math import ceil
from sys import maxsize, modules
from types import MappingProxyType
from typing import Any, ClassVar, Protocol
from uuid import UUID

from pydantic import BaseModel, root_validator, validator

from app.domain import commands as domain_commands
from app.domain import events as domain_events
from app.domain.base import (
    Base,
    Order,
    Payment,
    PaymentLog,
    PaymentRefund,
    PointUnit,
    Product,
    Sku,
    SkuLog,
    Transaction,
)
from app.utils import delivery_utils, geo_utils, time_util

from . import exceptions

logger = logging.getLogger(__name__)

LOGGING_PATH = "app.domain.transaction_delivery_order.models"


class Protocols:
    class AuthenticationMethod(Protocol):
        authentication_type: str
        membership_provider_name: str | None
        membership_user_identifiers: list | None

    class ExternalAuth(Protocol):
        external_auth_data: dict

    class DetailedUserData(Protocol):
        user_id: str
        nickname: str | None
        email: str | None
        gender: str | None
        age: int | None
        phone_number: str | None
        birthdate: str | None
        authentication_method: Protocols.AuthenticationMethod | None
        external_auth: Protocols.ExternalAuth | None


class Schemas:
    class PtIn(BaseModel):
        requested_point_amount: Decimal
        type: str
        priority: int | None
        sku_id: str | None
        card_id: str | None  # For Uzzim # For Uzzim Money, Not Settled Yet
        card_division: str | None  # For Uzzim
        conversion_ratio: Decimal = Decimal("1")
        point_provider_name: str
        point_provider_code: str
        external_user_id: str | None

    class PaymentOutstandings(BaseModel):
        pg_amount: Decimal
        point_units: list[Schemas.PtIn] = []

        class Config:
            json_encoders = {Decimal: lambda v: int(v)}

    class DeliveryTrackingDetails(BaseModel):
        time: int | None
        code: str | None
        timeString: str
        where: str
        kind: str
        level: int

    class DeliveryTrackingData(BaseModel):
        carrier_name: str = ""
        invoiceNo: str = ""
        level: int = -1
        trackingDetails: list[Schemas.DeliveryTrackingDetails] = []

    class PgToCancel(BaseModel):
        refund_amount: Decimal = Decimal("0")
        partial: bool = False
        message: str = ""
        processed: bool = False
        delivery_sku_id: str | None  # Only if partial set True

        @validator("delivery_sku_id")
        def validate_partiality(cls, v, values, **kwargs):
            if values["partial"] and not v:
                raise ValueError("Transaction Sku ID Must Be Given For Partial Cancellation")
            elif not values["partial"] and v:
                raise ValueError("Transaction Sku ID Must NOT Exist For Full Cancellation")
            return v

    class DeliveryPointUnitORM(BaseModel):
        create_dt: datetime | None

        point_provider_name: str | None
        point_provider_code: str | None

        id: str
        delivery_payment_id: str
        user_id: str
        type: str
        product_title: str
        channel_id: str

        init_point_amount: Decimal
        curr_point_amount: Decimal

        refund_amount: Decimal = Decimal("0")

        priority: int = 1

        reserved_amount: Decimal = Decimal("0")
        conversion_ratio: Decimal = Decimal("1")
        delivery_order_id: str = ""
        delivery_sku_id: str | None

        point_unit_type: str = ""
        processed: bool = False  # Must be changed
        is_new_id_required: bool = False  # In case Pg requires new id.

        class Config:
            orm_mode = True

    class PgPointParserOnCancellation(BaseModel):
        points_to_cancel: list[Schemas.DeliveryPointUnitORM] = []
        pg_to_cancel: Schemas.PgToCancel
        refund_context_sku_id: str | None

        class Config:
            json_encoders = {
                Decimal: lambda v: int(v),
            }

        @root_validator
        def check_if_any_data_given(cls, values):
            if not any((values["points_to_cancel"], values["pg_to_cancel"])):
                raise ValueError("None Of Expected Data Was Given!")
            return values


def sn_alphanum(length: int = 10) -> str:
    """
    generate sn with combination of
    Uppercase Alphabet and numbers 1 - 9
    """
    return "".join(secrets.choice(string.ascii_uppercase + string.digits[1:]) for _ in range(length))


@dataclass(eq=False)
class DeliveryTransaction(Transaction):
    class Status(str, Enum):
        PAYMENT_REQUIRED = "payment_required"
        PAYMENT_IN_PROGRESS = "payment_in_progress"
        PAID = "paid"
        FAILED = "failed"

    class OrderCancelationContext(str, Enum):
        MARKETPLACE_ORDER_CANCEL = "mp_order_cancel"
        BACKOFFICE_ORDER_CANCEL_ON_ClAIM = "backoffice_order_cancel_on_claim"
        BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_REJECTION = "backoffice_order_cancel_on_supplier_rejection"
        BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_CHECK_REJECTION = "backoffice_order_cancel_on_supplier_check_rejection"
        BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_SHIP_REJECTION = "backoffice_order_cancel_on_supplier_ship_rejection"
        BACKOFFICE_ORDER_CANCEL_ON_SPECIAL_CASE = "backoffice_order_cancel_on_special_case"

    class Currency(str, Enum):
        KRW = "KRW"  # 원화
        USD = "UDS"  # 달러

    # Metadata
    country: str
    user_id: str

    # Sender Shipping Info
    sender_name: str
    sender_phone: str
    sender_email: str
    delivery_note: str
    receiver_name: str
    receiver_phones: str
    receiver_address: str
    region_id: int
    postal_code: str

    # mapping
    delivery_orders: set[DeliveryOrder]
    delivery_payment: DeliveryPayment = field(init=False)
    delivery_payment_logs: set[DeliveryPaymentLog] = field(init=False, repr=False)
    type: str = "delivery"
    # application attribute
    events: deque = deque()

    def __post_init__(self):
        self.delivery_payment = DeliveryPayment(
            id=DeliveryPayment.sn_payment(),
            delivery_transaction_id=self.id,
            country=self.country,
            delivery_transaction=self,
        )
        for o in self.orders:
            for s in o.skus:
                s.transaction_id = self.id
                s.product.transaction_id = self.id
                if hasattr(s.product, "delivery_group"):
                    s.product.delivery_group.transaction_id = self.id

    paid_date: datetime | None = field(default=None)
    unsigned_secret_key: str = ""
    status: str = Status.PAYMENT_REQUIRED.value

    @property
    def orders(self):
        return self.delivery_orders

    @property
    def skus(self):
        return {sku for order in self.orders for sku in order.skus}

    @property
    def products(self):
        return {product for order in self.orders for product in order.products}

    @property
    def payment(self):
        return self.delivery_payment

    @payment.setter
    def payment(self, payment):
        self.delivery_payment = payment

    @property
    def payment_logs(self):
        return self.delivery_payment_logs

    @property
    def payment_refunds(self):
        return self.payment.payment_refunds

    @property
    def point_units(self):
        return self.payment.point_units

    @property
    def curr_transaction_pv_amount(self):
        return sum(o.curr_delivery_order_pv_amount for o in self.orders) or Decimal("0")

    @property
    def init_transaction_pv_amount(self):
        return sum(o.init_delivery_order_pv_amount for o in self.orders)

    @property
    def curr_transaction_delivery_fee(self):
        return sum(o.curr_delivery_order_delivery_fee for o in self.orders)

    @property
    def init_transaction_delivery_fee(self):
        return sum(o.init_delivery_order_delivery_fee for o in self.orders)

    @staticmethod
    def sn_transaction():
        return "DT-" + sn_alphanum(length=12)

    def update_status(self, *, context: str, **kwargs):
        if context == DeliveryTransaction.Status.PAID:
            _paid_date = time_util.current_time()
            self.status = context
            self.paid_date = _paid_date
            for o in self.orders:
                o.paid_date = _paid_date
                # TODO Status Set
        else:
            self.status = context
            self.paid_date = None
            for o in self.orders:
                o.paid_date = None

    def change_sku_status_in_bulk(
        self,
        msg: domain_events.OrderCompleted | domain_events.PGPaymentFailed | domain_events.PointUseRequestFailed,
    ):
        on_payment = self.status == DeliveryTransaction.Status.PAID
        status = msg.sku_status_to_change
        for sku in self.skus:
            sku.update_status(context=status)
            if on_payment:
                sku.request_status_date = time_util.current_time()
                sku.request_status = status
            sku.create_log(
                user_id=self.user_id,
                username=msg.marketplace_user_data.nickname,
                initiator_type=DeliverySkuLog.InitiatorType.SYSTEM,
            )

    @classmethod
    def _create_(cls, *, orders: set[DeliveryOrder], **kwargs) -> DeliveryTransaction:
        assert kwargs.get("shipping_info")
        delivery_order_info = kwargs["shipping_info"]

        delivery_transaction_data = dict(
            id=kwargs.get("delivery_transaction_id", cls.sn_transaction()),
            delivery_orders=orders,
        )

        delivery_transaction_data["currency"] = kwargs.get("currency", "KRW")
        delivery_transaction_data["country"] = kwargs.get("country", "")
        delivery_transaction_data["user_id"] = kwargs.get("user_id", "anonymous")

        # Shipping Info
        receiver_address = delivery_order_info.receiver_address if delivery_order_info is not None else None
        postal_code = receiver_address.postal_code
        delivery_transaction_data["postal_code"] = postal_code
        delivery_transaction_data["region_id"] = geo_utils.determine_area(postal_code=postal_code)
        delivery_transaction_data["receiver_address"] = " ".join((receiver_address.main, receiver_address.extra))

        delivery_transaction_data |= delivery_order_info.dict(exclude={"receiver_address", "postal_code"})
        delivery_transaction_data["user_id"] = kwargs.get("user_id", "anonymous")
        delivery_transaction = cls.from_kwargs(**delivery_transaction_data)
        return delivery_transaction

    @classmethod
    def _create(
        cls,
        msg: domain_commands.CreateOrder,
    ) -> tuple:
        order, *sub_obj = DeliveryOrder.create(msg=msg)

        _ = cls._create_(
            orders={order},
            shipping_info=msg.shipping_info,
            country=msg.channel_info.country,
            user_id=msg.marketplace_user_data.user_id,
        )
        return order, *sub_obj

    def create_payment_log_on_create(self, **kwargs):
        if transaction_id := kwargs.get("transaction_id"):
            kwargs["delivery_transaction_id"] = transaction_id
            del kwargs["transaction_id"]
        payment_log = DeliveryPaymentLog(id=DeliveryPaymentLog.sn_payment_log(), **kwargs)
        self.payment_logs.add(payment_log)

    def create_payment_log_on_cancel(
        self,
        pg_response: dict,
    ):
        payment = self.payment
        pg_type = payment.pg_setting_info["pg_type"]
        if pg_type == "smartro" and pg_response["ResultCode"] not in ("2001", "2211"):
            log_type = "cancellation_failed"
        elif pg_type == "kginicis" and pg_response.get("resultCode", "") not in ("00", "0000"):
            log_type = "cancellation_failed"
        else:
            log_type = "cancellation_succeeded"
        self.payment_logs.add(
            DeliveryPaymentLog.from_kwargs(
                id=DeliveryPaymentLog.sn_payment_log(),
                log_type=log_type,
                log=pg_response,
            )
        )

    def get_order(self, ref):
        return next((order for order in self.orders if order.id == ref), None)

    def get_shipping_info(self):
        return dict(
            sender_name=self.sender_name,
            sender_phone=self.sender_phone,
            sender_email=self.sender_email,
            delivery_note=self.delivery_note,
            receiver_name=self.receiver_name,
            receiver_phones=self.receiver_phones,
            receiver_address=self.receiver_address,
            region_id=self.region_id,
            postal_code=self.postal_code,
        )

    def detail_out(self):
        return [o.detail_out() for o in self.orders]

    def cancel_claim_out(self, refund_amount: Decimal, note: str) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliveryOrder(Order):
    # mappings
    delivery_transaction: DeliveryTransaction = field(init=False)
    delivery_products: set[DeliveryProduct] = field(init=False, repr=False)
    delivery_skus: set[DeliverySku] = field(default_factory=set)

    # meta data
    country: str = field(default="")
    paid_date: datetime | None = field(default=None)
    xmin: int = field(init=False, repr=False)

    settlement_frequency: int = 1
    delivery_transaction_id: str = field(init=False)

    # Init data
    user_id: str = "anonymous"
    status: str = DeliveryTransaction.Status.PAYMENT_REQUIRED.value

    init_delivery_order_pv_amount: Decimal = Decimal("0")
    init_delivery_order_delivery_fee: Decimal = Decimal("0")
    curr_delivery_order_pv_amount: Decimal = Decimal("0")
    curr_delivery_order_delivery_fee: Decimal = Decimal("0")

    currency: str = DeliveryTransaction.Currency.KRW.value

    # Application attribute
    events: deque = deque()

    @property
    def payment(self):
        return self.transaction.payment

    @property
    def transaction(self):
        return self.delivery_transaction

    @transaction.setter
    def transaction(self, transaction):
        self.delivery_transaction = transaction

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.delivery_transaction_id = transaction_id

    @property
    def skus(self):
        return self.delivery_skus

    @skus.setter
    def skus(self, skus):
        self.delivery_skus = skus

    @property
    def products(self):
        return self.delivery_products

    @products.setter
    def products(self, products):
        self.delivery_products = products

    @property
    def curr_order_pv_amount(self):
        return self.curr_delivery_order_pv_amount

    @property
    def init_order_pv_amount(self):
        return self.init_delivery_order_pv_amount

    @staticmethod
    def sn_order():
        return "O-" + sn_alphanum(length=13)

    @classmethod
    def _create(
        cls, msg: domain_commands.CreateOrder
    ) -> tuple[DeliveryOrder, set[DeliveryGroup], set[DeliveryProduct], set[DeliverySku]]:
        assert msg.shipping_info

        delivery_order_id = DeliveryOrder.sn_order()

        delivery_products, delivery_skus = DeliveryProduct.create(msg, delivery_order_id=delivery_order_id)
        delivery_groups = DeliveryGroup.create(
            delivery_product_data=delivery_products,
            postal_code=msg.shipping_info.receiver_address.postal_code,
        )
        delivery_order = cls.from_kwargs(
            id=delivery_order_id,
            delivery_skus=delivery_skus,
            country=msg.channel_info.country,
            user_id=msg.marketplace_user_data.user_id,
            settlement_frequency=msg.channel_info.settlement_frequency,
        )
        delivery_order.calculate_fees()
        delivery_order.products = delivery_products
        return delivery_order, delivery_groups, delivery_products, delivery_skus

    def calculate_fees(self):
        curr_delivery_order_pv_amount = Decimal("0")  # Constant
        curr_delivery_order_delivery_fee = Decimal("0")  # Variable
        delivery_products: set[DeliveryProduct] = set()
        delivery_groups: set[DeliveryGroup] = set()

        for sku in self.skus:
            # if sku.status not in [SkuStatus.UNSELECTED_IN_CART]:

            sku_pv_amount = Decimal("0")
            if sku.status not in sku.not_countable_statuses:
                sku_pv_amount = sku.quantity * Decimal(sku.sell_price)
            sku.sku_pv_amount = sku_pv_amount
            curr_delivery_order_pv_amount += sku_pv_amount

            delivery_products.add(sku.delivery_product)
            if sku.delivery_product.delivery_group:
                delivery_groups.add(sku.delivery_product.delivery_group)

        for prd in delivery_products:
            prd.calculate_delivery_fee()
            prd.calculate_product_pv_amount()

        for group in delivery_groups:
            # if group.supplier_delivery_group_id:
            group.calculate_delivery_fee()
            group.calculate_group_pv_amount()

            curr_delivery_order_delivery_fee += (
                group.curr_calculated_group_delivery_fee
                + group.curr_region_additional_delivery_fee
                - group.curr_group_delivery_discount
            )
        self.curr_delivery_order_pv_amount = curr_delivery_order_pv_amount
        self.curr_delivery_order_delivery_fee = curr_delivery_order_delivery_fee

    def set_payment_outstandings(self, points: list[Schemas.PtIn]):
        return self.payment.set_payment_outstandings(points=points)

    def initialize_calculated_delivery_fee(self, delivery_groups: set[DeliveryGroup]):
        self.init_delivery_order_delivery_fee = sum(
            (
                pdg.init_calculated_group_delivery_fee
                + pdg.init_region_additional_delivery_fee
                - pdg.init_group_delivery_discount
            )
            for pdg in delivery_groups
        ) or Decimal("0")
        self.init_delivery_order_pv_amount = sum(s.sku_pv_amount for s in self.skus) or Decimal("0")

    def detail_out(self) -> dict:  # type: ignore
        ...

    def dict(self) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliverySku(Sku):
    class Status(str, Enum):
        UNSELECTED_IN_CART = "unselected"
        PAYMENT_REQUIRED = "payment_required"  # 결제대기
        PAYMENT_FAIL_VALIDATION = "payment_fail_validation"  # 결제인증 실패 (PG 인증 실패)
        PAYMENT_FAIL_INVALID_PAYMENT_TRIAL = "payment_fail_invalid_payment_trial"  # 잘못된 방식의 결제 유도
        PAYMENT_FAIL_TIME_OUT = "payment_fail_time_out"  # 결제실패 (입금안함)
        PAYMENT_FAIL_ERROR = "payment_fail_error"  # 결제실패 (PG실패)
        PAYMENT_FAIL_POINT_ERROR = "payment_fail_point_error"  # 포인트 에러에 의한 결제 실패
        CHECK_REQUIRED = "check_required"  # 접수요망
        ORDER_FAIL_CHECK_REJECTED = "order_fail_check_rejected"  # 주문실패 (접수거절)
        SHIP_REQUIRED = "ship_required"  # 출고요망
        SHIP_OK = "ship_ok"  # 출고완료
        SHIP_OK_DIRECT_DELIVERY = "ship_ok_direct_delivery"  # 출고완료 (직접배송)
        ORDER_FAIL_SHIP_REJECTED = "order_fail_ship_rejected"  # 주문실패 (출고거절)
        SHIP_DELAY = "ship_delay"  # 출고지연
        DELIVERY_ING = "delivery_ing"  # 배송중
        DELIVERY_OK = "delivery_ok"  # 배송완료
        DELIVERY_DELAY = "delivery_delay"  # 배송지연
        ORDER_FINISHED = "order_finished"  # 구매확정
        ORDER_FINISHED_REVIEWED = "order_finished_reviewed"  # 구매확정(리뷰작성)
        REFUND_REQUESTED = "refund_requested"  # 반품요청
        REFUND_CHECKED = "refund_checked"  # 반품접수완료(동의대기중)
        REFUND_AGREED = "refund_agreed"  # 반품요청동의 (반품 수령 대기중)
        REFUND_FAIL_CHECK_REJECTED = "refund_fail_check_rejected"  # 반품거절 (접수거절)
        REFUND_FAIL_AGREE_REJECTED = "refund_fail_agree_rejected"  # 반품거절 (동의거절)
        REFUND_FAIL_INSPECT_REJECTED = "refund_fail_inspect_rejected"  # 반품거절 (검수부결)
        REFUND_FAIL_INSPECT_REJECTED_DO = "refund_fail_inspect_rejected_do"  # 반품거절 (검수부결 - 기존물품 배송완료)
        REFUND_FAIL_INSPECT_REJECTED_DD = "refund_fail_inspect_rejected_dd"  # 반품거절 (검수부결 - 기존물품 배송지연)
        REFUND_FAIL_RETURN_NO = "refund_fail_return_no"  # 반품실패 (반품 미수령)
        REFUND_RETURN_OK = "refund_return_ok"  # 반품수령완료
        REFUND_INSPECT_PASS = "refund_inspect_pass"  # 반품검수통과
        REFUND_FINISHED_NORMAL = "refund_finished_normal"  # 환불완료 (반품완료)
        REFUND_FINISHED_ORDER_CANCELED = "refund_finished_order_canceled"  # 환불완료 (주문취소)
        REFUND_FINISHED_ORDER_CANCELED_CONFIRMED = "refund_finished_order_canceled_confirmed"  # 환불완료 (주문취소확인)
        REFUND_FINISHED_CHECK_REJECTED = "refund_finished_check_rejected"  # 환불완료 (접수거절)
        REFUND_FINISHED_SHIP_REJECTED = "refund_finished_ship_rejected"  # 환불완료 (출고거절)
        REFUND_ING_ORDER_CANCELED = "refund_ing_order_canceled"  # 환불대기중 (주문취소)
        EXCHANGE_REQUESTED = "exchange_requested"  # 교환요청
        EXCHANGE_CHECKED = "exchange_checked"  # 교환접수완료(동의대기중)
        EXCHANGE_AGREED = "exchange_agreed"  # 교환동의 (교환품 수령 대기중)
        EXCHANGE_FAIL_CHECK_REJECTED = "exchange_fail_check_rejected"  # 교환거절 (접수거절)
        EXCHANGE_FAIL_AGREE_REJECTED = "exchange_fail_agree_rejected"  # 교환거절 (동의거절)
        EXCHANGE_FAIL_INSPECT_REJECTED = "exchange_fail_inspect_rejected"  # 교환거절 (검수부결)
        EXCHANGE_FAIL_INSPECT_REJECTED_DO = "exchange_fail_inspect_rejected_do"  # 교환거절 (검수부결 - 기존물품 배송완료)
        EXCHANGE_FAIL_INSPECT_REJECTED_DD = "exchange_fail_inspect_rejected_dd"  # 교환거절 (검수부결 - 기존물품 배송지연)
        EXCHANGE_FAIL_RESHIP_REJECTED = "exchange_fail_reship_rejected"  # 교환거절 (재출고거절)
        EXCHANGE_FAIL_RESHIP_REJECTED_DO = "exchange_fail_reship_rejected_do"  # 교환거절 (새물품 출고거절-기존물품 재배송 완료)
        EXCHANGE_FAIL_RESHIP_REJECTED_DD = "exchange_fail_reship_rejected_dd"  # 교환거절 (새물품 출고거절-기존물품 재배송 지연)
        EXCHANGE_FAIL_RETURN_NO = "exchange_fail_return_no"  # 교환실패 (교환품 미수령)
        EXCHANGE_RETURN_OK = "exchange_return_ok"  # 교환품수령완료
        EXCHANGE_INSPECT_PASS = "exchange_inspect_pass"  # 교환품검수통과
        EXCHANGE_RESHIP_OK = "exchange_reship_ok"  # 교환새물품 출고완료
        EXCHANGE_RESHIP_DELAY = "exchange_reship_delay"  # 교환새물품 출고지연
        EXCHANGE_DELIVERY_ING = "exchange_delivery_ing"  # 교환새물품 배송중
        EXCHANGE_DELIVERY_OK = "exchange_delivery_ok"  # 교환새물품 배송완료
        EXCHANGE_DELIVERY_DELAY = "exchange_delivery_delay"  # 교환새물품 배송지연

    class DeliveryFeeMethodOnReturnClaim(str, Enum):
        DEFAULT = "default"  # 반품이 아닐경우
        CUSTOMER_CHARGE_CARD_CANCEL = "customer_charge_card_cancel"  # 고객부담 (카드취소시 환불금액에서 배송비 차감, 정산 시 가산)
        CUSTOMER_CHARGE_CASH_COMPLETE = "customer_charge_cash_complete"  # 고객부담 (현금수령완료, 정산 시 가산)
        CUSTOMER_CHARGE_DIRECT_TRANSFER = "customer_charge_direct_transfer"  # 고객부담 (고객이 서플에게 직접 이체)
        CUSTOMER_CHARGE_DIRECT_DELIVERY = "customer_charge_direct_delivery"  # 고객부담 (고객이 직접 배송)
        CHANNEL_CHARGE = "channel_charge"  # 채널부담 (정산 시 가산)
        SUPPLIER_CHARGE = "supplier_charge"  # 파트너부담 (카드취소시 환불금액 전체를 고객이 받음)

    class DeliveryFeeMethodOnExchangeClaim(str, Enum):
        DEFAULT = "default"  # 교환이 아닐경우
        CUSTOMER_CHARGE_CASH_COMPLETE = "customer_charge_cash_complete"  # 고객부담 (현금수령완료, 정산 시 가산)
        CUSTOMER_CHARGE_DIRECT_TRANSFER = "customer_charge_direct_transfer"  # 고객부담 (고객이 서플에게 직접 이체)
        CHANNEL_CHARGE = "channel_charge"  # 채널부담 (정산 시 가산)
        SUPPLIER_CHARGE = "supplier_charge"  # 파트너부담

    class SkuClaimGetContext(str, Enum):
        RETURN = "return"
        EXCHANGE = "exchange"
        CANCEL = "cancel"
        NONE = "none"

    # mappings
    delivery_product: DeliveryProduct
    delivery_sku_logs: list[DeliverySkuLog] = field(default_factory=list)
    delivery_order: DeliveryOrder = field(init=False)
    delivery_product_id: str = field(init=False, repr=False)
    delivery_order_id: str = field(init=False, repr=False)
    delivery_group_id: str | None = field(default=None, init=False)
    delivery_transaction_id: str = field(init=False)

    def __eq__(self, other):
        if not isinstance(other, Sku):
            return False
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __post_init__(self):
        self.product_class = self.product.product_class
        self.product_id = self.product.id
        self.order_id = self.product.order_id
        self.product_title = self.product.title
        self.supplier_portal_id = self.product.supplier_portal_id
        self.supplier_name = self.product.supplier_name

        self.id = self.sn_sku()

    # Meta Info
    user_id: str = field(default="")

    country: str = field(default="")
    supplier_portal_id: str = field(init=False)
    supplier_name: str = field(init=False)

    product_title: str = field(init=False)
    xmin: int = field(init=False, repr=False)

    sellable_sku_id: str = ""
    request_status_date: datetime = field(init=False, repr=False)

    # Init data
    id: str

    master_sku_id: str = ""

    title: str = ""
    image: str = ""
    status: str = Status.PAYMENT_REQUIRED.value
    request_status: str = Status.PAYMENT_REQUIRED.value
    carrier_code: str = ""
    carrier_number: str = ""
    sell_price: Decimal = Decimal("0")
    supply_price: Decimal = Decimal("0")

    cost: Decimal = Decimal("0")
    product_class: str = ""  # from delivery_product
    base_delivery_fee: Decimal = Decimal("0")

    timesale_applied: bool = field(default=False)
    quantity: int = 0

    purchased_finalized_date: datetime | None = None
    calculated_exchange_delivery_fee: Decimal = Decimal("0")
    delivery_tracking_data: str = ""
    # pg_paid_amount :Decimal = Decimal("0") # sell_price  * quantity - point_amount - coupon_amount
    # pg_amount_for_refund: Decimal = Decimal("0") #

    refund_delivery_fee_method: str = DeliveryFeeMethodOnReturnClaim.DEFAULT.value
    exchange_delivery_fee_method: str = DeliveryFeeMethodOnExchangeClaim.DEFAULT.value

    accumulated_delivery_fee: dict = field(default_factory=dict)  # patch
    unsigned_secret_key: str = ""

    options: list = field(default_factory=list)

    # Delivery Related Data
    delivery_tracking: DeliveryTracking | None = None
    delivery_tracking_id: str = ""

    # Application Attribute
    calculated_sku_delivery_fee: Decimal = Decimal("0")
    calculated_refund_delivery_fee: Decimal = Decimal("0")
    sku_pv_amount: Decimal = Decimal("0")
    events: deque = deque()

    _not_countable_statuses: ClassVar[frozenset] = frozenset(
        {
            Status.UNSELECTED_IN_CART,
            Status.REFUND_FINISHED_NORMAL,  # 반품
            Status.REFUND_FINISHED_ORDER_CANCELED,  # 주문취소
            Status.REFUND_FINISHED_ORDER_CANCELED_CONFIRMED,  # 주문취소 확인
            Status.REFUND_FINISHED_CHECK_REJECTED,  # 접수거절 의한 환불
            Status.REFUND_FINISHED_SHIP_REJECTED,  # 출고거절에 의한 환불
            Status.PAYMENT_FAIL_VALIDATION,  # 결제인증 실패 (PG 인증 실패)
            Status.PAYMENT_FAIL_INVALID_PAYMENT_TRIAL,  # 잘못된 방식의 결제 유도
            Status.PAYMENT_FAIL_TIME_OUT,  # 결제실패 (입금안함)
            Status.PAYMENT_FAIL_ERROR,  # 결제실패 (PG실패)
            Status.PAYMENT_FAIL_POINT_ERROR,  # 포인트 에러에 의한 결제 실패
        }
    )
    _status_mapper: ClassVar[MappingProxyType] = MappingProxyType(
        {
            DeliveryTransaction.OrderCancelationContext.MARKETPLACE_ORDER_CANCEL.value: (
                Status.REFUND_FINISHED_ORDER_CANCELED.value
            ),
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_ClAIM.value: (
                Status.REFUND_FINISHED_NORMAL.value
            ),
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_CHECK_REJECTION.value: (
                Status.REFUND_FINISHED_CHECK_REJECTED.value
            ),
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_SHIP_REJECTION.value: (
                Status.REFUND_FINISHED_SHIP_REJECTED.value
            ),
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SPECIAL_CASE.value: (
                Status.REFUND_FINISHED_ORDER_CANCELED.value
            ),
        }
    )
    _refundable_cases: ClassVar[frozenset] = frozenset(
        {
            Status.PAYMENT_REQUIRED,
            Status.CHECK_REQUIRED,
        }
    )
    _request_status_date_updatables: ClassVar[frozenset] = frozenset(
        {
            Status.PAYMENT_REQUIRED,
            Status.CHECK_REQUIRED,
            Status.EXCHANGE_REQUESTED,
            Status.REFUND_REQUESTED,
        }
    )

    @property
    def order(self):
        return self.delivery_order

    @property
    def order_id(self):
        return self.delivery_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.delivery_order_id = order_id

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @transaction_id.setter
    def transaction_id(self, ref):
        self.delivery_transaction_id = ref

    @property
    def product(self):
        return self.delivery_product

    @property
    def product_id(self):
        return self.delivery_product_id

    @product_id.setter
    def product_id(self, product_id):
        self.delivery_product_id = product_id

    @property
    def sku_logs(self):
        return self.delivery_sku_logs

    @sku_logs.setter
    def sku_logs(self, sku_logs):
        self.delivery_sku_logs = sku_logs

    @property
    def not_countable_statuses(self):
        return self._not_countable_statuses

    @property
    def status_mapper(self):
        return self._status_mapper

    @property
    def refundable_cases(self):
        return self._refundable_cases

    @property
    def request_status_date_updatables(self):
        return self._request_status_date_updatables

    @classmethod
    def _create(
        cls,
        msg: domain_commands.CreateOrder,
        *,
        sellable_sku_data: list[dict],
        delivery_product: DeliveryProduct,
        **kwargs,
    ):
        delivery_skus = set()
        for data in sellable_sku_data:
            sku_data = copy.copy(data)
            quantity = msg.sellable_sku_qty_mapper.get(sku_data["id"])
            if not quantity:
                raise Exception

            sku_data |= dict(
                sellable_sku_qty_mapper=msg.sellable_sku_qty_mapper,
                country=msg.channel_info.country,
                user_id=msg.marketplace_user_data.user_id,
                delivery_product=delivery_product,
                sellable_sku_id=sku_data["id"],
                quantity=quantity,
                id=cls.sn_sku(),
            )
            del sku_data["left_inventory_count"]
            del sku_data["left_inventory_status"]
            del sku_data["sku"]

            delivery_sku = cls.from_kwargs(**sku_data)
            delivery_skus.add(delivery_sku)
        return delivery_skus

    @staticmethod
    def sn_sku():
        return "OPS-" + sn_alphanum(length=11)

    def get_refund_amount_on_cs_modal(self, *, expected_refund_amount: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        payment = self.order.payment
        point_units_to_substract, refund_amount = self.settle_refund_amount(
            payment=payment, expected_refund_amount=expected_refund_amount
        )
        payment.set_partial_cancelation_outstandings(
            point_units_to_subtract=point_units_to_substract,
            sku_id=self.id,
            refund_amount=refund_amount,
            note="Whatever",
            marketplace_user_data=...,  # TODO
            generating_event_required=False,
        )
        cancellation_out_standings: Schemas.PgPointParserOnCancellation = payment.get_cancelation_outstandings()
        pg_refund_amount = cancellation_out_standings.pg_to_cancel.refund_amount
        sku_point_refund_amount = Decimal("0")
        point_refund_amount = Decimal("0")
        for p in cancellation_out_standings.points_to_cancel:
            if p.delivery_sku_id:
                sku_point_refund_amount += p.refund_amount
            else:
                point_refund_amount += p.refund_amount
        return pg_refund_amount, sku_point_refund_amount, point_refund_amount

    def set_delivery_tracking_data(self, initial_delivery_data: dict):
        delivery_tracking_data = Schemas.DeliveryTrackingData(**initial_delivery_data)
        self.delivery_tracking_data = delivery_tracking_data.json()

    def set_disbursement_expecting_dates(self, *, settlement_frequency: int):
        expecting_start_date, expecting_end_date = time_util.locate_start_and_end_dates_on_frequency(
            confirm_date=self.purchased_finalized_date, settlement_frequency=settlement_frequency, country=self.country
        )
        self.disbursement_expecting_start_date = expecting_start_date
        self.disbursement_expecting_end_date = expecting_end_date

    def get_delivery_fee_difference(self, refund_context: str):
        delivery_group = self.delivery_product.delivery_group
        if not delivery_group:
            return self.quantity * self.sell_price

        # Calculation
        delivery_group.calculate_delivery_fee_on_group()

        current_calculated_delivery_fee = (
            delivery_group.curr_calculated_group_delivery_fee
            + delivery_group.curr_region_additional_delivery_fee
            - delivery_group.curr_group_delivery_discount
        )

        # Status Change
        current_status = self.status
        self.status = self.status_mapper[refund_context]

        # Recalculation
        delivery_group.calculate_delivery_fee_on_group()
        newly_calculated_delivery_fee = (
            delivery_group.curr_calculated_group_delivery_fee
            + delivery_group.curr_region_additional_delivery_fee
            - delivery_group.curr_group_delivery_discount
        )

        delivery_fee_difference = current_calculated_delivery_fee - newly_calculated_delivery_fee

        # Status back to current
        self.status = current_status
        return delivery_fee_difference

    def calculate_refund_price_on_partial_cancelation(self, *, refund_context: str) -> Decimal | None:
        assert self.delivery_product
        delivery_group = self.delivery_product.delivery_group
        if not delivery_group:
            # TODO What if subscription applies?
            return self.sell_price * self.quantity

        if refund_context in (
            DeliveryTransaction.OrderCancelationContext.MARKETPLACE_ORDER_CANCEL.value,
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_CHECK_REJECTION.value,
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_SHIP_REJECTION.value,
            DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_ClAIM.value,
        ):
            if refund_context == DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_ClAIM.value:
                self.calculate_return_delivery_fee()

            return self._calculate_refund_price_on_partial_cancelation(refund_context=refund_context)
        return None

    def calculate_return_delivery_fee(self):
        # To return delivery fee calculation for SKU being in 'refund flow'
        if self.status not in (
            DeliverySku.Status.DELIVERY_OK,
            DeliverySku.Status.REFUND_REQUESTED,
            DeliverySku.Status.REFUND_CHECKED,
            DeliverySku.Status.REFUND_AGREED,
            DeliverySku.Status.REFUND_RETURN_OK,
            DeliverySku.Status.REFUND_INSPECT_PASS,
        ):
            return None
        assert self.delivery_product
        assert self.delivery_product.delivery_group
        self.delivery_product.delivery_group.calculate_delivery_fee_on_group()
        is_delivered_for_free = self.check_if_delivered_for_free()
        self._calculate_delivery_fee_on_return_check(is_delivered_for_free=is_delivered_for_free)

    def _calculate_refund_price_on_partial_cancelation(self, *, refund_context: str):
        """
        Calculate expeceted refund amount for SKU being not shipped yet
        """
        assert self.delivery_product
        assert self.delivery_product.delivery_group
        delivery_group = self.delivery_product.delivery_group

        delivery_fee_difference = self.get_delivery_fee_difference(refund_context=refund_context)
        # Special Special Case
        if delivery_fee_difference < 0 and (self.sell_price * self.quantity) < abs(delivery_fee_difference):
            return None

        # Backoffice Case
        if (
            refund_context
            in (
                DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_CHECK_REJECTION,
                DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_SHIP_REJECTION,
            )
            and delivery_fee_difference < 0
        ):
            delivery_group.loss_fee = abs(delivery_fee_difference)
            delivery_fee_difference = Decimal("0")

        return self.sell_price * self.quantity + delivery_fee_difference

    def settle_refund_amount(
        self, *, payment: DeliveryPayment, expected_refund_amount
    ) -> tuple[list[DeliveryPointUnit], Decimal]:
        assert self.delivery_product
        point_units_to_subtract: list[DeliveryPointUnit]

        if self.is_last_sku():
            refund_amount = expected_refund_amount

            delivery_group = self.delivery_product.delivery_group

            # Further deduct loss fee in case the condition
            if delivery_group:
                refund_amount -= delivery_group.loss_fee

            if self.refund_delivery_fee_method == self.DeliveryFeeMethodOnReturnClaim.CUSTOMER_CHARGE_CARD_CANCEL:
                refund_amount -= self.calculated_refund_delivery_fee

            # Take point units that are either transactional or points units with the same group id
            point_units_to_subtract = []
            for point_unit in payment.point_units:
                if point_unit.delivery_sku_id is None:
                    point_units_to_subtract.append(point_unit)
                if point_unit.delivery_group_id and point_unit.delivery_group_id == self.delivery_group_id:
                    point_units_to_subtract.append(point_unit)
                    if point_unit.delivery_sku_id != self.id:
                        refund_amount += point_unit.curr_point_amount

        else:
            refund_amount = self.calculate_max_limit_refundable_amount_on_partial_cancelation(
                refund_amount=expected_refund_amount
            )
            point_units_to_subtract = [
                point_unit
                for point_unit in payment.point_units
                if point_unit.delivery_sku_id is None or point_unit.delivery_sku_id == self.id
            ]

        return point_units_to_subtract, refund_amount

    def get_refund_context(self, refund_context: str) -> str:
        res = ""
        if refund_context == DeliveryTransaction.OrderCancelationContext.MARKETPLACE_ORDER_CANCEL:
            if self.status in self.refundable_cases:
                res = refund_context
        elif refund_context == DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_ClAIM:
            if self.status == DeliverySku.Status.REFUND_INSPECT_PASS:
                res = refund_context
        elif (
            refund_context == DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_REJECTION
        ):
            if self.status == DeliverySku.Status.ORDER_FAIL_CHECK_REJECTED:
                res = DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_CHECK_REJECTION
            elif self.status == DeliverySku.Status.ORDER_FAIL_SHIP_REJECTED:
                res = DeliveryTransaction.OrderCancelationContext.BACKOFFICE_ORDER_CANCEL_ON_SUPPLIER_SHIP_REJECTION
        return res

    def is_last_sku(self):
        delivery_product = self.delivery_product
        delivery_group = delivery_product.delivery_group

        if delivery_group:
            for product in delivery_group.products:
                for sku in product.skus:
                    if sku == self:
                        continue
                    if sku.status in (DeliverySku.Status.ORDER_FINISHED, DeliverySku.Status.ORDER_FINISHED_REVIEWED):
                        return False
                    if sku.status not in sku.not_countable_statuses:
                        return False
            else:
                return True
        return True

    def calculate_max_limit_refundable_amount_on_partial_cancelation(self, *, refund_amount: Decimal):
        assert self.order
        payment = self.order.payment
        max_limit_refundable_amount = payment.curr_pg_amount + sum(
            pu.curr_point_amount
            for pu in payment.point_units
            if not pu.delivery_sku_id or pu.delivery_sku_id == self.id
        )
        final_refund_amount = (
            max_limit_refundable_amount if refund_amount >= max_limit_refundable_amount else refund_amount
        )
        return final_refund_amount

    def claim_update(
        self,
        *,
        context: str,
    ):
        self.update_status(context=context)
        if self.status == DeliverySku.Status.ORDER_FINISHED:
            self.events.append(domain_events.OrderConfirmed(sku_ids={self.id}, is_auto=False))

    def update_status(self, *, context: str, **kwargs):
        self.status = context
        if self.status in self.request_status_date_updatables:
            self.request_status = context
            self.request_status_date = time_util.current_time()
        if self.status == DeliverySku.Status.ORDER_FINISHED:
            self.purchased_finalized_date = time_util.current_time()
        if self.status in (
            DeliverySku.Status.REFUND_FAIL_RETURN_NO,
            DeliverySku.Status.REFUND_FAIL_INSPECT_REJECTED_DO,
            DeliverySku.Status.REFUND_FAIL_AGREE_REJECTED,
        ):
            self.refund_delivery_fee_method = self.DeliveryFeeMethodOnReturnClaim.DEFAULT

    def fastforward_update(self, *, log_data):
        if self.status == DeliverySku.Status.SHIP_OK:
            self.update_status(context=DeliverySku.Status.DELIVERY_ING.value)
            self.create_log(**log_data)
            self.update_status(context=DeliverySku.Status.DELIVERY_OK.value)
            self.create_log(**log_data)

        elif self.status == DeliverySku.Status.EXCHANGE_RESHIP_OK:
            self.update_status(context=DeliverySku.Status.EXCHANGE_DELIVERY_ING.value)
            self.create_log(**log_data)
            self.update_status(context=DeliverySku.Status.EXCHANGE_DELIVERY_OK.value)
            self.create_log(**log_data)

        elif self.status == DeliverySku.Status.EXCHANGE_FAIL_INSPECT_REJECTED:
            self.update_status(context=DeliverySku.Status.EXCHANGE_FAIL_INSPECT_REJECTED_DO.value)
            self.create_log(**log_data)

        elif self.status == DeliverySku.Status.EXCHANGE_FAIL_RESHIP_REJECTED:
            self.update_status(context=DeliverySku.Status.EXCHANGE_FAIL_RESHIP_REJECTED_DO.value)
            self.create_log(**log_data)

        elif self.status == DeliverySku.Status.REFUND_FAIL_INSPECT_REJECTED:
            self.update_status(context=DeliverySku.Status.REFUND_FAIL_INSPECT_REJECTED_DO.value)
            self.create_log(**log_data)

    def _calculate_delivery_fee_on_exchange_check(self):
        assert self.delivery_product
        assert self.delivery_product.delivery_group
        delivery_product = self.delivery_product
        delivery_group = self.delivery_product.delivery_group  # ! what if group not exists?
        pricing_method = delivery_product.delivery_pricing_method

        # For unit charge, get the number of boxes to pack the sku in question
        box_num: int = 1
        if pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE:
            box_num = ceil(self.quantity / delivery_product.charge_standard)

        self.calculated_exchange_delivery_fee = delivery_product.exchange_delivery_fee * box_num

        # For round-trip delivery, double the fee for region additional delivery fee.
        region_additional_delivery_fee = delivery_group.get_original_region_additional_delivery_fee() * 2

        # In case of "NON-GROUPED" delivery AND pricing method set to unit charge
        if (
            not delivery_group.supplier_delivery_group_id
            and pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE
        ):
            region_additional_delivery_fee *= box_num

        self.calculated_exchange_delivery_fee += region_additional_delivery_fee

    def _calculate_delivery_fee_on_return_check(self, is_delivered_for_free: bool):
        assert self.delivery_product
        assert self.delivery_product.delivery_group
        # Check if the delivery price for given SKU has been discounted (for free)
        delivery_group = self.delivery_product.delivery_group

        # !Check if calculated_product_delivery_fee of product that the given sku belongs is free(0)
        # !or the given sku was delivered for free
        if is_delivered_for_free:
            self.calculated_refund_delivery_fee = self.delivery_product.refund_delivery_fee_if_free_delivery
        else:
            self.calculated_refund_delivery_fee = self.delivery_product.refund_delivery_fee

        # If delivery pricing method is not free if the sku is delivered not free
        box_num = 1
        pricing_method = self.delivery_product.delivery_pricing_method
        if pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE:
            box_num = ceil(self.quantity / self.delivery_product.charge_standard)

        self.calculated_refund_delivery_fee *= box_num

        region_additional_delivery_fee = delivery_group.get_original_region_additional_delivery_fee()
        if (
            not delivery_group.supplier_delivery_group_id
            and pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE
        ):
            region_additional_delivery_fee *= box_num

        self.calculated_refund_delivery_fee += region_additional_delivery_fee

    def check_if_delivered_for_free(self):
        assert self.delivery_product
        assert self.delivery_product.delivery_group
        delivery_group = self.delivery_product.delivery_group
        current_product_calculated_delivery_fee: Decimal = Decimal("0")
        price_list = []
        for delivery_product in delivery_group.products:
            if delivery_product.number_of_skus_to_consider > 0:
                price_list.append(delivery_product.curr_calculated_product_delivery_fee)

            if delivery_product == self.delivery_product:
                current_product_calculated_delivery_fee = delivery_product.curr_calculated_product_delivery_fee

        number_of_duplicate_delivery_fees = price_list.count(current_product_calculated_delivery_fee)

        max_delivery_fees = max(price_list) if len(price_list) > 0 else 0
        if max_delivery_fees == current_product_calculated_delivery_fee and number_of_duplicate_delivery_fees == 1:
            return False
        return True

    def create_log(self, **kwargs):
        self.delivery_sku_logs.append(
            DeliverySkuLog.from_kwargs(id=DeliverySkuLog.sn_sku_log(), delivery_sku=self, **kwargs)
        )

    def get_sku_log(self, ref: str) -> DeliverySkuLog | None:
        return next((log for log in self.delivery_sku_logs if log.id == ref), None)

    # TODO -> view decorator
    def validate_ship_mgt(self, *, order_id: str, carrier_code: str, carrier_number: str) -> bool:
        if self.order_id != order_id:
            return False
        if not any((carrier_code, carrier_number)):
            return False
        if not carrier_number:
            if carrier_code != "999":
                return False
            else:
                return True
        if not carrier_number.isdigit():
            return False
        if not delivery_utils.carrier_code_and_name.get(carrier_code, None):
            return False
        return True

    @staticmethod
    def sort_status(status_count_mapper: dict[str, int], context: str | None = None):
        """
        Sort Out Sku Status And Its Aggregated Count Depending On The Requested Context
        """
        # TODO -> lucian
        return status_count_mapper

    def get_anonymous_access_key(self):  # type: ignore
        ...

    def claim_history_out(self):
        ...

    def claim_out(self, context: SkuClaimGetContext | None = None) -> dict:  # type: ignore
        ...

    def dict(self) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliverySkuLog(SkuLog):
    class InitiatorType(str, Enum):
        SUPPLIER = "supplier"  # 공급자
        CHANNEL_OWNER = "channel_owner"  # 채널 오너
        USER = "user"  # 고객
        SYSTEM = "system"

    # Meta Info
    delivery_transaction_id: str = field(init=False)
    delivery_order_id: str = field(init=False)
    delivery_sku_id: str = field(init=False)
    status: str = field(init=False)
    xmin: int = field(init=False, repr=False)

    # Post Init
    def __post_init__(self):
        assert self.delivery_sku
        sku = self.sku

        self.supplier_portal_id = sku.supplier_portal_id
        self.user_id = sku.user_id
        self.order_id = sku.order_id
        self.transaction_id = sku.transaction_id
        self.sku_id = sku.id
        self.status = sku.status

    # Init data
    user_id: str = field(init=False)  # market place user id, can be same as initiator_id, can be not
    supplier_portal_id: str = field(init=False)
    delivery_sku: DeliverySku | None = None
    initiator_id: str = ""

    user_notes: dict = field(default_factory=dict)
    supplier_notes: dict = field(default_factory=dict)

    initiator_name: str = ""
    initiator_type: str = InitiatorType.SUPPLIER.value
    initiator_info: dict = field(default_factory=dict)

    @property
    def sku(self):
        return self.delivery_sku

    @sku.setter
    def sku(self, sku):
        self.delivery_sku = sku

    @property
    def order_id(self):
        return self.delivery_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.delivery_order_id = order_id

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @transaction_id.setter
    def transaction_id(self, transaction_id):
        self.delivery_transaction_id = transaction_id

    @staticmethod
    def sn_sku_log():
        return "OSL-" + sn_alphanum(length=11)

    def dict(self) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliveryProduct(Product):
    class ProductClass(str, Enum):
        TANGIBLE = "tangible"
        INTANGIBLE = "intangible"
        GIFTCARD = "giftcard"

    class PricingMethod(str, Enum):
        FREE = "free"
        UNIT_CHARGE = "unit_charge"
        CONDITIONAL_CHARGE = "conditional_charge"
        REGULAR_CHARGE = "regular_charge"

    # Meta Info
    country: str = ""

    delivery_group_id: str = field(init=False, repr=False)
    delivery_order: DeliveryOrder | None = field(default=None, repr=False)
    delivery_order_id: str = field(default="")
    delivery_transaction_id: str = field(init=False)
    xmin: int = field(init=False, repr=False)

    # Init data
    id: str
    delivery_group: DeliveryGroup | None = None
    sellable_product_id: str = ""
    sellable_product_sn: str = ""
    supplier_portal_id: str = ""  # sellable product table

    is_vat: bool = field(default=False)  # sellable product table (for disbursement goods)

    master_product_id: str = ""
    master_product_sn: str = ""

    title: str = ""
    images: list = field(default_factory=list)

    init_calculated_product_delivery_fee: Decimal = field(default=Decimal("0"))

    supplier_name: str = ""
    # Delivery_info
    delivery_info: dict = field(default_factory=dict)

    base_delivery_fee: Decimal = Decimal("0")
    exchange_delivery_fee: Decimal = Decimal("0")
    refund_delivery_fee: Decimal = Decimal("0")
    refund_delivery_fee_if_free_delivery: Decimal = Decimal("0")
    delivery_pricing_unit: str | None = None

    delivery_pricing_method: str = ""
    charge_standard: Decimal = Decimal("0")

    product_class: str = ProductClass.TANGIBLE.value
    sku_count: int = 1  # SKU의 갯수, Cart에서 사용
    number_of_skus_to_consider: int = 0
    number_of_quantity_to_consider: int = 0
    delivery_skus: set[DeliverySku] = field(default_factory=set)

    # Application Attribute
    curr_calculated_product_delivery_fee: Decimal = Decimal("0")
    product_pv_amount: Decimal = field(default=Decimal("0"))

    @property
    def order(self):
        return self.delivery_order

    @property
    def order_id(self):
        return self.delivery_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.delivery_order_id = order_id

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @transaction_id.setter
    def transaction_id(self, ref):
        self.delivery_transaction_id = ref

    @property
    def skus(self):
        return self.delivery_skus

    @skus.setter
    def skus(self, skus):
        self.delivery_skus = skus

    @staticmethod
    def sn_product():
        return "OP-" + sn_alphanum(length=12)

    @classmethod
    def _create(
        cls, msg: domain_commands.CreateOrder, delivery_order_id=None, **kwargs
    ) -> tuple[set[DeliveryProduct], set[DeliverySku]]:
        delivery_products: set[DeliveryProduct] = set()
        delivery_skus: set[DeliverySku] = set()
        delivery_order_id = delivery_order_id or DeliveryOrder.sn_order()

        for product_data in msg.delivery_products_to_order:
            product_data = copy.copy(product_data)
            delivery_info = copy.copy(product_data.get("delivery_info", {}))
            delivery_product_id = cls.sn_product()
            product_data |= dict(
                exchange_delivery_fee=delivery_info.get("exchange_delivery_fee", Decimal("0")),
                refund_delivery_fee=delivery_info.get("refund_delivery_fee", Decimal("0")),
                refund_delivery_fee_if_free_delivery=delivery_info.get(
                    "refund_delivery_fee_if_free_delivery", Decimal("0")
                ),
                delivery_pricing_unit=delivery_info.get("delivery_pricing_unit", None),
                sellable_product_id=product_data["id"],
                sellable_product_sn=product_data["sn"],
                delivery_order_id=delivery_order_id,
                delivery_product_id=delivery_product_id,
                country=msg.channel_info.country,
                id=delivery_product_id,
            )

            delivery_product = cls.from_kwargs(**product_data)
            skus = DeliverySku._create(
                msg,
                sellable_sku_data=product_data["sellable_skus"],
                delivery_product=delivery_product,
                **kwargs,
            )
            delivery_product.skus = skus
            delivery_products.add(delivery_product)
            delivery_skus.update(skus)
        return delivery_products, delivery_skus

    def calculate_product_pv_amount(self):
        product_pv_amount = Decimal("0")

        for delivery_sku in self.skus:
            if delivery_sku.status not in delivery_sku.not_countable_statuses:
                product_pv_amount += delivery_sku.sku_pv_amount
        self.product_pv_amount = product_pv_amount

    def calculate_delivery_fee(self):
        # In case all skus belonging to this product have status that are not delivery-fee-countable
        number_of_skus_to_consider = 0
        number_of_quantity_to_consider = 0
        product_pv_amount = Decimal("0")

        for sku in self.skus:
            if sku.status not in sku.not_countable_statuses:
                number_of_skus_to_consider += 1
                number_of_quantity_to_consider += 1
                product_pv_amount += sku.sku_pv_amount
        # In case this product is not for delivery
        self.number_of_skus_to_consider = number_of_skus_to_consider
        self.number_of_quantity_to_consider = number_of_quantity_to_consider
        self.product_pv_amount = product_pv_amount

        if not self.delivery_info:
            self.curr_calculated_product_delivery_fee = Decimal("0")
            return None

        if not number_of_skus_to_consider:
            self.curr_calculated_product_delivery_fee = Decimal("0")
            return None

        # In case some/all skus are delivery-fee-countable

        charge_standard = self.charge_standard

        if pricing_method := self.delivery_pricing_method:
            if pricing_method == DeliveryProduct.PricingMethod.CONDITIONAL_CHARGE:
                if self.product_pv_amount >= charge_standard:
                    self.curr_calculated_product_delivery_fee = Decimal("0")
                else:
                    self.curr_calculated_product_delivery_fee = self.base_delivery_fee
            elif pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE:
                self.curr_calculated_product_delivery_fee = self.base_delivery_fee * Decimal(
                    ceil(self.number_of_quantity_to_consider / charge_standard)
                )
            elif pricing_method == DeliveryProduct.PricingMethod.REGULAR_CHARGE:
                self.curr_calculated_product_delivery_fee = self.base_delivery_fee
            elif pricing_method == DeliveryProduct.PricingMethod.FREE:
                self.curr_calculated_product_delivery_fee = Decimal("0")
            else:
                raise exceptions.InvalidPricingMethod
        else:
            raise exceptions.InvalidPricingMethod

    def initialize_calculated_delivery_fee(self):
        self.init_calculated_product_delivery_fee = self.curr_calculated_product_delivery_fee

    def dict(self) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliveryGroup(Base):
    # Meta Info
    country: str = field(init=False)
    delivery_order_id: str = field(default="")

    xmin: int = field(init=False, repr=False)

    # Post Init
    def _map_relationship(self):
        for delivery_product in self.products:
            delivery_product.delivery_group = self
            delivery_product.delivery_group_id = self.id

            for delivery_sku in delivery_product.skus:
                delivery_sku.delivery_group_id = self.id

    # Init data
    id: str
    supplier_delivery_group_id: str = ""
    supplier_delivery_group_name: str = ""
    region_id: int = 1

    supplier_portal_id: str = ""
    supplier_name: str = ""
    calculation_method: str = ""
    region_division_level: int | None = None
    division2_fee: int = 0
    division3_jeju_fee: int = 0
    division3_outside_jeju_fee: int = 0
    is_additional_pricing_set: bool = False

    loss_fee: Decimal = Decimal("0")
    delivery_products: set[DeliveryProduct] = field(default_factory=set)

    init_calculated_group_delivery_fee: Decimal = field(default=Decimal("0"))
    init_region_additional_delivery_fee: Decimal = field(default=Decimal("0"))
    init_group_delivery_discount: Decimal = field(default=Decimal("0"))

    # Application Attribute
    curr_calculated_group_delivery_fee: Decimal = Decimal("0")  # sum of curr_calculated_product_delivery_fee
    original_region_additional_delivery_fee: Decimal = Decimal("0")
    curr_region_additional_delivery_fee: Decimal = Decimal("0")
    curr_group_delivery_discount: Decimal = Decimal(
        "0"
    )  # curr_calculated_group_delivery_fee - max(curr_calculated_product_delivery_fee)
    group_pv_amount: Decimal = Decimal("0")
    processing_finalized_date: datetime | None = field(default=None, init=False)

    @property
    def products(self):
        return self.delivery_products

    @property
    def order_id(self):
        return self.delivery_order_id

    @order_id.setter
    def order_id(self, order_id):
        self.order_id = order_id

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @transaction_id.setter
    def transaction_id(self, ref):
        self.delivery_transaction_id = ref

    @staticmethod
    def sn_group():
        return "PGD-" + sn_alphanum(length=11)

    @classmethod
    def _create(
        cls, *, delivery_product_data: list[DeliveryProduct], postal_code: str, **kwargs
    ) -> list[DeliveryGroup]:
        delivery_groups: set[DeliveryGroup] = set()

        for product in delivery_product_data:
            delivery_info: dict = product.delivery_info
            if not delivery_info:
                continue
            pgd_data: dict[str, Any] = {}

            pgd_data["region_id"] = geo_utils.determine_area(postal_code=postal_code)

            pgd_data["country"] = product.country
            pgd_data["id"] = cls.sn_group()
            pgd_data["delivery_order_id"] = product.order_id
            pgd_data["supplier_portal_id"] = product.supplier_portal_id
            pgd_data["supplier_name"] = product.supplier_name

            pgd_data["division2_fee"] = delivery_info["division2_fee"]
            pgd_data["division3_jeju_fee"] = delivery_info["division3_jeju_fee"]
            pgd_data["division3_outside_jeju_fee"] = delivery_info["division3_outside_jeju_fee"]
            pgd_data["is_additional_pricing_set"] = delivery_info["is_additional_pricing_set"]  # Check
            pgd_data["region_division_level"] = delivery_info["region_division_level"]
            if delivery_info.get("is_group_delivery", False):
                pgd_data["supplier_delivery_group_id"] = delivery_info["delivery_group_id"]
                pgd_data["supplier_delivery_group_name"] = delivery_info.get("name")
                pgd_data["calculation_method"] = delivery_info["calculation_method"]

            delivery_group = cls.from_kwargs(**pgd_data)
            if existing_group_delivery := next(
                (
                    pgd
                    for pgd in delivery_groups
                    if pgd.supplier_delivery_group_id == delivery_group.supplier_delivery_group_id
                    and pgd.supplier_delivery_group_id
                ),
                None,
            ):
                existing_group_delivery.products.add(product)
            else:
                delivery_group.products.add(product)
                delivery_groups.add(delivery_group)

                delivery_group.products.add(product)
                delivery_groups.add(delivery_group)
        for g in delivery_groups:
            g._map_relationship()
        return list(delivery_groups)

    def calculate_delivery_fee(self):
        is_group_delivery: bool = bool(self.supplier_delivery_group_id)
        calculated_group_delivery_fee = Decimal("0")
        group_delivery_discount = Decimal("0")
        region_additional_delivery_fee = Decimal("0")
        is_group_calculation_required = sum(p.number_of_quantity_to_consider for p in self.products) > 0
        if is_group_calculation_required:
            region_additional_delivery_fee = self.get_original_region_additional_delivery_fee()
            if is_group_delivery:
                price_list = []
                calculation_method: str = self.calculation_method
                for product in self.products:
                    calculated_product_delivery_fee = product.curr_calculated_product_delivery_fee
                    calculated_group_delivery_fee += calculated_product_delivery_fee
                    if product.number_of_skus_to_consider != 0:
                        price_list.append(calculated_product_delivery_fee)

                method = getattr(modules["builtins"], calculation_method)
                if len(price_list) > 0:
                    group_delivery_fee = method(price_list)
                    group_delivery_discount = calculated_group_delivery_fee - group_delivery_fee
                else:
                    calculated_group_delivery_fee = Decimal("0")
                    group_delivery_discount = Decimal("0")
                    region_additional_delivery_fee = Decimal("0")

            else:
                only_product: DeliveryProduct = next(prod for prod in self.products)
                if only_product.number_of_skus_to_consider == 0:
                    region_additional_delivery_fee = Decimal("0")
                else:
                    if only_product.delivery_pricing_method == DeliveryProduct.PricingMethod.UNIT_CHARGE.value:
                        units = ceil(
                            sum(
                                sku.quantity
                                for sku in only_product.skus
                                if sku.status not in sku.not_countable_statuses
                            )
                            / only_product.charge_standard
                        )

                        region_additional_delivery_fee = self.get_original_region_additional_delivery_fee() * units
                    calculated_group_delivery_fee = only_product.curr_calculated_product_delivery_fee

        self.curr_calculated_group_delivery_fee = calculated_group_delivery_fee
        self.curr_group_delivery_discount = group_delivery_discount
        self.curr_region_additional_delivery_fee = region_additional_delivery_fee

    def calculate_group_pv_amount(self):
        for prd in self.products:
            self.group_pv_amount += prd.product_pv_amount

    def calculate_delivery_fee_on_group(self):
        for prd in self.products:
            prd.calculate_delivery_fee()
        else:
            self.calculate_delivery_fee()

    def initialize_calculated_delivery_fee(self):
        self.init_calculated_group_delivery_fee = self.curr_calculated_group_delivery_fee
        self.init_region_additional_delivery_fee = self.curr_region_additional_delivery_fee
        self.init_group_delivery_discount = self.curr_group_delivery_discount

    def get_original_region_additional_delivery_fee(self) -> Decimal:  # type: ignore
        ...

    def dict(self) -> dict:  # type: ignore
        ...


# Payment
@dataclass(eq=False)
class DeliveryPayment(Payment):
    id: str
    country: str

    delivery_transaction: DeliveryTransaction
    xmin: int = field(init=False, repr=False)
    delivery_transaction_id: str = field(default="", repr=False)

    outstandings: str = field(default="", init=False)
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
    delivery_point_units: set[DeliveryPointUnit] = field(default_factory=set)

    delivery_payment_refunds: list[DeliveryPaymentRefund] = field(default_factory=list)

    # Application attribute
    events: deque = deque()

    @staticmethod
    def sn_payment():
        return "DP-" + sn_alphanum(length=12)

    @property
    def transaction(self):
        return self.delivery_transaction

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @property
    def orders(self):
        return self.transaction.orders

    @property
    def point_units(self):
        return self.delivery_point_units

    @property
    def payment_refunds(self):
        return self.delivery_payment_refunds

    def get_payment_outstandings(self) -> Schemas.PaymentOutstandings | None:
        if self.outstandings:
            return Schemas.PaymentOutstandings.parse_raw(self.outstandings)
        return None

    def set_payment_outstandings(self, points: list[Schemas.PtIn]) -> tuple[bool, bool]:
        # TODO refactoring to allow for subscription, bulk create of orders.
        pg_amount = Decimal("0")
        for o in self.transaction.orders:
            pg_amount += o.curr_order_pv_amount
            pg_amount += o.curr_delivery_order_delivery_fee
        else:
            pg_amount -= sum(pt.requested_point_amount for pt in points) or Decimal("0")

        self.outstandings = Schemas.PaymentOutstandings(point_units=points, pg_amount=pg_amount).json()

        pg_processing_required = pg_amount > 0
        point_processing_required = sum(pt.requested_point_amount for pt in points) > 0
        return pg_processing_required, point_processing_required

    def get_cancelation_outstandings(self) -> Schemas.PgPointParserOnCancellation:
        return Schemas.PgPointParserOnCancellation.parse_raw(self.outstandings)

    def set_partial_cancelation_outstandings(
        self,
        *,
        sku_id: str,
        point_units_to_subtract: list[DeliveryPointUnit],
        refund_amount,
        marketplace_user_data: Protocols.DetailedUserData,
        note: str,
        refund_context: str = "",
        generating_event_required: bool = True,
        **kwargs,
    ) -> None:
        # Check If The Given Sku Is the Last SKU In Product Group Delivery

        original_refund_amount = copy.copy(refund_amount)

        # Prioritize What Points To Subtract
        sku_point_units: list[Schemas.DeliveryPointUnitORM] = []
        delivery_point_units: list[Schemas.DeliveryPointUnitORM] = []
        for pu in point_units_to_subtract:
            point_unit_schema = Schemas.DeliveryPointUnitORM.from_orm(pu)
            sku_point_units.append(point_unit_schema) if pu.delivery_sku_id else delivery_point_units.append(
                point_unit_schema
            )

        sku_point_units.sort(key=lambda x: x.priority)
        delivery_point_units.sort(key=lambda x: x.priority)

        point_units: list = sku_point_units + delivery_point_units
        charge_amount_on_pg = Decimal("0")
        index_for_trx_point_unit = maxsize

        order = 0

        for order, point_unit in enumerate(point_units, 1):
            if point_unit.delivery_sku_id is None and order < index_for_trx_point_unit:
                index_for_trx_point_unit = order - 1

            if (refund_amount - point_unit.curr_point_amount) > Decimal("0"):
                refund_amount -= point_unit.curr_point_amount
                point_unit.refund_amount += point_unit.curr_point_amount
                point_unit.curr_point_amount = Decimal("0")

            else:
                # No PG Call Path
                point_unit.curr_point_amount = point_unit.curr_point_amount - refund_amount
                point_unit.refund_amount += refund_amount
                break
        else:
            # If the loop takes this statement, it means there is an amount to pay on PG
            charge_amount_on_pg = refund_amount

        # Take Only Part Of Point Units
        sliced_point_units = point_units[:order]
        if index_for_trx_point_unit == maxsize:
            sku_point_to_cancel = sliced_point_units
        else:
            sku_point_to_cancel = sliced_point_units[:index_for_trx_point_unit]
        delivery_point_to_cancel = sliced_point_units[index_for_trx_point_unit:]
        self.outstandings = Schemas.PgPointParserOnCancellation(
            points_to_cancel=sku_point_to_cancel + delivery_point_to_cancel,
            pg_to_cancel=Schemas.PgToCancel(
                refund_amount=charge_amount_on_pg, partial=True, message=note, delivery_sku_id=sku_id
            ),
            refund_context_sku_id=sku_id,
        ).json()

        if generating_event_required:
            self.events.append(
                domain_events.PartialOrderCancelRequested(
                    transaction_id=self.transaction.id,
                    order_id=next(o.id for o in self.orders),
                    sku_id_for_cancelation=sku_id,
                    marketplace_user_data=marketplace_user_data,
                    note=note,
                    pg_refund_amount=charge_amount_on_pg,
                    point_refund_amount=(original_refund_amount - charge_amount_on_pg),
                    pg_cancel_required=charge_amount_on_pg > Decimal("0"),
                    point_cancel_required=len(sliced_point_units) > 0,
                    refund_context=refund_context,
                )
            )

        return None

    def set_full_cancelation_outstandings(
        self, *, pg_refund_amount: Decimal, marketplace_user_data: Protocols.DetailedUserData, note: str, **kwargs
    ):
        point_refund_amount = Decimal("0")
        points_to_cancel: set = set()

        # Set refund amount
        for pu in self.point_units:
            if pu.curr_point_amount == Decimal("0"):
                continue
            point_refund_amount += pu.curr_point_amount
            pu.refund_amount = pu.curr_point_amount

        points_to_cancel = self.point_units

        outstandings: Schemas.PgPointParserOnCancellation = Schemas.PgPointParserOnCancellation(
            pg_to_cancel=Schemas.PgToCancel(refund_amount=pg_refund_amount, partial=False, message=note),
            points_to_cancel=points_to_cancel,
        )
        self.outstandings = outstandings.json()
        self.events.append(
            domain_events.OrderCancelRequested(
                marketplace_user_data=marketplace_user_data,
                note=note,
                transaction_id=self.delivery_transaction_id,
                order_id=next(o.id for o in self.orders),
                point_cancel_required=next(
                    (pu for pu in self.point_units if pu.curr_point_amount != Decimal("0")), None
                )
                is not None,
                sku_ids_for_cancelation={sku.id for o in self.orders for sku in o.skus},
                pg_cancel_required=pg_refund_amount > Decimal("0"),
                pg_refund_amount=pg_refund_amount,
                point_refund_amount=point_refund_amount,
                refund_context=DeliveryTransaction.OrderCancelationContext.MARKETPLACE_ORDER_CANCEL.value,
            )
        )

    def deduct_point_units(self):
        outstandings = self.get_cancelation_outstandings()
        point_unit_id_refund_amount_mapper = {pu.id: pu for pu in outstandings.points_to_cancel}

        for point_unit in self.point_units:
            if point_unit.id in point_unit_id_refund_amount_mapper:
                refund_amount = point_unit_id_refund_amount_mapper[point_unit.id].refund_amount
                point_unit.curr_point_amount -= refund_amount
                point_unit.refund_amount += refund_amount
                point_unit_id_refund_amount_mapper[point_unit.id].processed = True

        self.outstandings = outstandings.json()

    def set_outstandings_on_point_request_fail(self, *, marketplace_user_data: Protocols.DetailedUserData):
        # Check Pg Cancel Required
        outstandings = self.get_payment_outstandings()
        assert outstandings

        pg_cancel_required: bool = False

        if outstandings.pg_amount:
            pg_cancel_required = True

        # Reset the outstandings
        self.outstandings = Schemas.PaymentOutstandings(pg_amount=self.curr_pg_amount).json()

        # Raise an event
        event = domain_events.PointUseRequestFailed(
            transaction_id=self.transaction.id,
            marketplace_user_data=marketplace_user_data,
            delivery_sku_ids={pu.delivery_sku_id for pu in self.point_units if pu.delivery_sku_id},
            pg_cancel_required=pg_cancel_required,
        )
        self.events.append(event)

        # Alternative to rollback operation
        self.point_units.clear()

    def process_pg_complete_order_result(
        self,
        res: str,
        cmd: domain_commands.CompletePg,
    ) -> None:
        if res.endswith("invalid_payment_trial"):
            return None

        outstandings = self.get_payment_outstandings()
        assert outstandings

        point_processing_required = outstandings.point_units != []

        sku_status_to_change: str = ""
        event: domain_events.Message | None = None

        # FAIL Case
        if self.transaction.status == DeliveryTransaction.Status.FAILED:
            if res.endswith("validation_fail"):
                sku_status_to_change = DeliverySku.Status.PAYMENT_FAIL_VALIDATION.value
                logger.exception(
                    "Payment Validation Fail!: {}\nPG type:{}".format(
                        self.transaction_id, self.pg_setting_info["pg_type"]  # TODO -> locate id
                    )
                )
            else:
                sku_status_to_change = DeliverySku.Status.PAYMENT_FAIL_ERROR.value
                logger.exception(
                    "Payment Fail!: {}\nPG type:{}".format(self.transaction_id, self.pg_setting_info["pg_type"])
                )
            event = domain_events.PGPaymentFailed(
                transaction_id=self.transaction_id,
                marketplace_user_data=cmd.marketplace_user_data,
                sku_status_to_change=sku_status_to_change,
            )

        # SUCCESS Case
        elif self.transaction.status == DeliveryTransaction.Status.PAID:
            # Set Pg amount
            self.init_pg_amount = outstandings.pg_amount
            self.curr_pg_amount = outstandings.pg_amount

            sku_status_to_change = DeliverySku.Status.CHECK_REQUIRED.value

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

    def create_point_units(self):
        outstandings = self.get_payment_outstandings()
        assert outstandings is not None

        for pt in outstandings.point_units:
            assert pt.priority
            assert pt.type
            assert pt.conversion_ratio
            # assert pt.external_user_id
            if pt.requested_point_amount <= Decimal("0"):
                continue
            point_amount = pt.requested_point_amount
            point_unit_type = "t" if pt.sku_id is None else "s"
            delivery_sku = next((sku for o in self.orders for sku in o.skus if sku.id == pt.sku_id), None)
            product_title: str = ""
            delivery_product_id: str = ""
            delivery_group_id: str | None = None

            if point_unit_type == "s":
                assert delivery_sku
                assert delivery_sku.product_title
                delivery_product_id = delivery_sku.delivery_product_id
                product_title = delivery_sku.product_title
                delivery_group_id = delivery_sku.delivery_product.delivery_group_id

            self.point_units.add(
                DeliveryPointUnit(
                    delivery_payment_id=self.id,
                    user_id=self.transaction.user_id,
                    external_user_id=pt.external_user_id,
                    delivery_transaction_id=self.transaction.id,
                    country=self.country,
                    init_point_amount=point_amount,
                    curr_point_amount=point_amount,
                    priority=pt.priority,
                    id=DeliveryPointUnit.sn_sku_point_unit() if pt.sku_id else DeliveryPointUnit.sn_order_point_unit(),
                    type=pt.type,
                    point_unit_type=point_unit_type,
                    product_title=product_title,
                    conversion_ratio=pt.conversion_ratio,
                    point_provider_name=pt.point_provider_name,
                    point_provider_code=pt.point_provider_code,
                    delivery_sku_id=pt.sku_id,
                    delivery_product_id=delivery_product_id,
                    delivery_group_id=delivery_group_id,
                )
            )

    def update_point_paid_amount_on_payment(
        self, *, marketplace_user_data: Protocols.DetailedUserData, is_cart_order: bool = False, **kwargs
    ) -> None:
        for pu in self.point_units:
            self.init_point_amount += pu.curr_point_amount
            self.curr_point_amount += pu.curr_point_amount
        self.events.append(
            domain_events.OrderCompleted(
                transaction_id=self.transaction_id,
                marketplace_user_data=marketplace_user_data,
                delivery_sku_ids={sku.id for o in self.orders for sku in o.skus},
                is_cart_order=is_cart_order,
            )
        )

    def create_refund_logs(self):
        outstandings = self.get_cancelation_outstandings()
        # Logging Point Refunds
        for pu in outstandings.points_to_cancel:
            if pu.refund_amount > 0:
                self.payment_refunds.append(
                    DeliveryPaymentRefund(
                        delivery_transaction_id=self.transaction.id,
                        payment_id=self.id,
                        delivery_sku_id=pu.delivery_sku_id,
                        point_amount_for_refund=pu.refund_amount,
                        point_unit_id=pu.id,
                        point_unit_create_dt=pu.create_dt,
                        refund_context_sku_id=outstandings.refund_context_sku_id,
                    )
                )
        # Logging Pg Refunds
        if outstandings.pg_to_cancel.refund_amount > Decimal("0"):
            self.payment_refunds.append(
                DeliveryPaymentRefund(
                    pg_amount_for_refund=outstandings.pg_to_cancel.refund_amount,
                    payment_id=self.id,
                    delivery_transaction_id=self.transaction.id,
                    refund_context_sku_id=outstandings.refund_context_sku_id,
                )
            )

        # Reinitialize outstandings
        self.outstandings = ""

    def set_confirm_date_on_sku_point(self, *, sku: Sku):
        """
        Method to update sku point to confirmed upon 'order-confirmed' event
        """
        sku_point_unit = next(
            (pu for pu in self.point_units if pu.delivery_sku_id and pu.delivery_sku_id == sku.id),
            None,
        )
        if sku_point_unit:
            sku_point_unit.confirm_date = time_util.current_time()

    def payment_card_info_formatter(self) -> dict:  # type: ignore
        ...

    def dict(self) -> dict:  # type: ignore
        ...


@dataclass(eq=False)
class DeliveryPaymentRefund(PaymentRefund):
    create_dt: datetime = field(init=False)
    # meta
    payment_id: str
    delivery_transaction_id: str
    id: str = field(default="")
    point_unit_id: str | None = field(default=None)
    point_unit_create_dt: datetime | None = field(default=None)
    delivery_payment: DeliveryPayment | None = field(default=None)
    xmin: int = field(init=False, repr=False)

    def __post_init__(self):
        self.id = self.sn_payment_refund()

    refund_context_sku_id: str | None = field(default=None)
    delivery_sku_id: str | None = field(default=None)
    point_amount_for_refund: Decimal | None = None
    pg_amount_for_refund: Decimal | None = None
    coupon_amount_for_refund: Decimal | None = None

    @staticmethod
    def sn_payment_refund():
        return "PR-" + sn_alphanum(length=12)


@dataclass(eq=False)
class DeliveryPointUnit(PointUnit):
    point_provider_name: str
    point_provider_code: str

    # mappings
    delivery_payment_id: str
    id: str
    user_id: str
    type: str

    init_point_amount: Decimal
    curr_point_amount: Decimal

    country: str
    delivery_transaction_id: str
    product_title: str = ""
    xmin: int = field(init=False, repr=False)

    create_dt: datetime = field(init=False)
    update_dt: datetime = field(init=False)
    confirm_date: datetime | None = field(default=None)

    refund_amount: Decimal = Decimal("0")
    delivery_payment: DeliveryPayment = field(init=False)
    reserved_amount: Decimal = Decimal("0")
    conversion_ratio: Decimal = Decimal("1")

    delivery_sku_id: str | None = None
    delivery_product_id: str | None = None
    delivery_group_id: str | None = None

    point_unit_type: str = field(default="t")
    external_user_id: str | None = ""
    priority: int = field(default=1)

    @property
    def transaction(self):
        return self.delivery_payment.transaction

    @property
    def transaction_id(self):
        return self.delivery_transaction_id

    @property
    def sku_id(self):
        return self.delivery_sku_id

    @classmethod
    def sn_order_point_unit(cls):
        return "TPU-" + sn_alphanum(length=11)

    @classmethod
    def sn_sku_point_unit(cls):
        return "SPU-" + sn_alphanum(length=11)

    def update_disbursement_status(self, context):
        self.status = context


@dataclass(eq=False)
class DeliveryPaymentLog(PaymentLog):
    delivery_transaction_id: str = field(default="", repr=False)
    delivery_transaction: DeliveryTransaction = field(init=False)
    xmin: int = field(init=False, repr=False)

    log: dict = field(default_factory=dict)

    @staticmethod
    def sn_payment_log():
        return "TPL-" + sn_alphanum(length=11)


@dataclass(eq=False)
class DeliveryTracking(Base):
    id: str = field(init=False)
    carrier_code: str
    carrier_number: str
    level: int = 0
    tracking_details: list = field(default_factory=list)
    delivery_skus: set[DeliverySku] = field(default_factory=set)
    xmin: int = field(init=False, repr=False)

    def __post_init__(self):
        self.id = self.sn_delivery_tracking()

    @property
    def skus(self):
        return self.delivery_skus

    @staticmethod
    def sn_delivery_tracking():
        return "DT-" + sn_alphanum(length=12)

    def __eq__(self, other):
        if not isinstance(other, DeliveryTracking):
            return False
        return all((self.carrier_code == other.carrier_code, self.carrier_number == other.carrier_number))

    def __hash__(self):
        return hash(self.carrier_code + self.carrier_number)

    def get_delivery_tracking_info(self) -> dict:
        return dict(
            carrier_name=delivery_utils.carrier_code_and_name[self.carrier_code],
            invoiceNo=self.carrier_number,
            level=self.level,
            trackingDetails=self.tracking_details,
        )

    def set_carrier_info(self):
        for transction_sku in self.skus:
            transction_sku.carrier_number = self.carrier_number
            transction_sku.carrier_code = self.carrier_code

    def update_tracking_detail(self, tracking_detail: dict):
        current_level = tracking_detail["level"]
        self.level = current_level if self.level < current_level else self.level

        tracking_details = copy.copy(self.tracking_details)
        tracking_details.append(tracking_detail)
        self.tracking_details = tracking_details

    def update_skus_on_delivery_tracking_callback(self):
        for delivery_sku in self.skus:
            # Case1 - shipping has been done
            if self.level == 6:
                if delivery_sku.status == DeliverySku.Status.DELIVERY_ING:
                    delivery_sku.status = DeliverySku.Status.DELIVERY_OK.value
                elif delivery_sku.status == DeliverySku.Status.EXCHANGE_FAIL_INSPECT_REJECTED:
                    delivery_sku.status = DeliverySku.Status.EXCHANGE_FAIL_INSPECT_REJECTED_DO.value
                elif delivery_sku.status == DeliverySku.Status.REFUND_FAIL_INSPECT_REJECTED:
                    delivery_sku.status = DeliverySku.Status.REFUND_FAIL_INSPECT_REJECTED_DO.value
                elif delivery_sku.status == DeliverySku.Status.EXCHANGE_DELIVERY_ING:
                    delivery_sku.status = DeliverySku.Status.EXCHANGE_DELIVERY_OK.value
                else:
                    continue
                delivery_sku.create_log(
                    initiator_id=str(UUID(int=0)),
                    initiator_name="system",
                )

            # Case2 - shipping is underway
            elif self.level in range(2, 6):
                if delivery_sku.status == DeliverySku.Status.SHIP_OK:
                    delivery_sku.status = DeliverySku.Status.DELIVERY_ING.value
                elif delivery_sku.status == DeliverySku.Status.EXCHANGE_RESHIP_OK:
                    delivery_sku.status = DeliverySku.Status.EXCHANGE_DELIVERY_ING.value
                else:
                    continue
                delivery_sku.create_log(
                    initiator_id=str(UUID(int=0)),
                    initiator_name="system",
                )
