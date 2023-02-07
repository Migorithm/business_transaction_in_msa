from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from inspect import signature

from app.domain.exceptions import WrongArgumentsForEvent


@dataclass(repr=True, eq=False)
class Base(ABC):
    """
    Base Class For Domain Models
    """

    id: str
    create_dt: datetime = field(init=False, repr=False)
    update_dt: datetime = field(init=False, repr=False)

    @classmethod
    def from_kwargs(cls, **kwargs):
        cls_fields = {f for f in signature(cls).parameters}

        native_args, new_args = {}, {}
        for name, val in kwargs.items():
            if name in cls_fields:
                native_args[name] = val
            else:
                new_args[name] = val
        ret = cls(**native_args)

        for new_name, new_val in new_args.items():
            setattr(ret, new_name, new_val)
        return ret

    def __gt__(self, other):
        if not isinstance(other, Base):
            return False
        return self.create_dt > other.create_dt

    def __eq__(self, other):
        if not isinstance(other, Base):
            return False
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def _to_dict(self):
        if hasattr(self, "__slots__"):
            return {v: getattr(self, v) for v in self.__slots__}
        return self.__dict__

    def dict(self):
        res = {}
        for k in self.__dataclass_fields__.keys():
            res[k] = getattr(self, k)
        return res

    @classmethod
    def create(cls, *args, **kwargs):
        return cls._create(*args, **kwargs)

    @classmethod
    def _create(cls, *args, **kwargs):
        raise NotImplementedError


class PointBase:
    type: str
    priority: int
    id: str

    def __eq__(self, other):
        if not isinstance(other, PointBase):
            return False
        if self.id != other.id:
            return False
        if self.type != other.type:
            return False
        return self.priority == other.priority

    def __gt__(self, other):
        if not isinstance(other, PointBase):
            return False
        return self.priority > other.priority

    def __hash__(self):
        return hash((self.priority, self.type))

    @classmethod
    def from_kwargs(cls, **kwargs):
        cls_fields = {f for f in signature(cls).parameters}

        native_args, new_args = {}, {}
        for name, val in kwargs.items():
            if name in cls_fields:
                native_args[name] = val
            else:
                new_args[name] = val
        ret = cls(**native_args)

        for new_name, new_val in new_args.items():
            setattr(ret, new_name, new_val)
        return ret

    @classmethod
    def create(cls, *args, **kwargs):
        return cls._create(*args, **kwargs)

    @classmethod
    def _create(cls, *args, **kwargs):
        ...


class Transaction(Base):
    sender_name: str
    sender_phone: str
    sender_email: str
    status: str
    paid_date: datetime | None
    user_id: str
    currency: str
    events: deque
    type: str

    # @abstractmethod
    # def apply(self, arg):
    #     ...

    @abstractmethod
    def create_payment_log_on_create(self, **kwargs):
        ...

    @abstractmethod
    def create_payment_log_on_cancel(
        self,
        pg_response: dict,
    ):
        ...

    @abstractmethod
    def update_status(self, *, context, **kwargs):
        """
        To Update TRX Status. It May Or May Not Include Different Operation Depending On
        The Target Status Requested
        """

    @staticmethod
    @abstractmethod
    def sn_transaction(*args, **kwargs):
        ...

    @property
    @abstractmethod
    def orders(self) -> set[Order]:
        ...

    @abstractmethod
    def get_order(self, ref):
        ...

    @property
    @abstractmethod
    def skus(self) -> set[Sku]:
        ...

    @property
    @abstractmethod
    def payment(self) -> Payment:
        ...

    @payment.setter
    @abstractmethod
    def payment(self, payment):
        ...

    @property
    @abstractmethod
    def payment_logs(self):
        ...

    @property
    @abstractmethod
    def payment_refunds(self):
        ...

    @property
    @abstractmethod
    def point_units(self):
        ...

    @abstractmethod
    def change_sku_status_in_bulk(self, msg):
        ...

    @property
    @abstractmethod
    def curr_transaction_pv_amount(self):
        ...

    @property
    @abstractmethod
    def init_transaction_pv_amount(self):
        ...


@dataclass(eq=False)
class Order(Base):
    id: str
    create_dt: datetime = field(init=False, repr=False)
    update_dt: datetime = field(init=False, repr=False)
    channel_id: str = field(init=False)
    user_id: str = field(init=False)
    sender_name: str = field(init=False)
    sender_phone: str = field(init=False)
    sender_email: str = field(init=False)
    currency: str = field(init=False)

    @staticmethod
    @abstractmethod
    def sn_order(*args, **kwargs):
        ...

    @abstractmethod
    def set_payment_outstandings(self, points):
        ...

    @property
    @abstractmethod
    def payment(self):
        ...

    @property
    @abstractmethod
    def skus(self):
        ...

    @skus.setter
    @abstractmethod
    def skus(self, skus):
        ...

    @property
    @abstractmethod
    def curr_order_pv_amount(self):
        ...

    @property
    @abstractmethod
    def init_order_pv_amount(self):
        ...

    @property
    @abstractmethod
    def transaction(self):
        ...

    @transaction.setter
    @abstractmethod
    def transaction(self, transaction):
        ...

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @transaction_id.setter
    @abstractmethod
    def transaction_id(self, transaction_id):
        ...

    @abstractmethod
    def calculate_fees(self) -> None:
        ...

    @staticmethod
    @abstractmethod
    def precalculate_on_checkout(*args, **kwargs):  # type: ignore
        ...

    @staticmethod
    @abstractmethod
    def dict(*args, **kwargs) -> dict:  # type: ignore
        ...


class Sku(Base):
    channel_name: str
    channel_id: str
    sellable_sku_id: str
    quantity: int
    product_title: str
    title: str
    status: str

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @transaction_id.setter
    @abstractmethod
    def transaction_id(self, ref):
        ...

    @property
    @abstractmethod
    def order_id(self):
        ...

    @order_id.setter
    @abstractmethod
    def order_id(self, order_id):
        ...

    @property
    @abstractmethod
    def order(self):
        ...

    @property
    @abstractmethod
    def sku_logs(self):
        ...

    @sku_logs.setter
    @abstractmethod
    def sku_logs(self, sku_logs):
        ...

    @staticmethod
    @abstractmethod
    def sn_sku(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given SKU
        """

    @staticmethod
    @abstractmethod
    def _create(*args, **kwargs):
        """
        A Method To Bulk-Create Sku Objects
        """

    @abstractmethod
    def set_disbursement_expecting_dates(self, *, settlement_frequency):
        """
        A Method To Set The Expected Disbursement Expecting Dates
        """

    @abstractmethod
    def calculate_refund_price_on_partial_cancelation(self, *, refund_context):
        """
        When Cancellation Request On SKU Is Received, This Method Will Be Called
        To Calculate Refund Price
        """

    @abstractmethod
    def update_status(self, *, context, **kwargs):
        """
        To Update Sku Status. It May Or May Not Include Different Operation Depending On
        The Target Status Requested
        """

    @abstractmethod
    def update_disbursement_status(self, *, context: str):
        """
        To Update Sku Disbursement Status. It May Or May Not Include Different Operation Depending On
        The Target Status Requested
        """

    @abstractmethod
    def commission_prices(self):
        """
        Get Commision prices for disbursement.
        """

    @abstractmethod
    def create_log(self, **kwargs):
        """
        Create Sku Log
        """

    @staticmethod
    @abstractmethod
    def dict(*args, **kwargs) -> dict:
        """
        A Method To Dictify The Given Object
        """


@dataclass(eq=False)
class SkuLog(Base):
    @property
    @abstractmethod
    def sku(self):
        ...

    @sku.setter
    @abstractmethod
    def sku(self, sku):
        ...

    @property
    @abstractmethod
    def order_id(self):
        ...

    @order_id.setter
    @abstractmethod
    def order_id(self, order_id):
        ...

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @transaction_id.setter
    @abstractmethod
    def transaction_id(self, transaction_id):
        ...

    @staticmethod
    @abstractmethod
    def sn_sku_log(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given SKU
        """

    @staticmethod
    @abstractmethod
    def dict(*args, **kwargs) -> dict:
        """
        A Method To Dictify The Given Object
        """


class Product(Base):
    title: str

    @property
    @abstractmethod
    def order(self):
        ...

    @property
    @abstractmethod
    def order_id(self):
        ...

    @order_id.setter
    @abstractmethod
    def order_id(self, order_id):
        ...

    @property
    @abstractmethod
    def skus(self):
        ...

    @skus.setter
    @abstractmethod
    def skus(self, skus):
        ...

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @transaction_id.setter
    @abstractmethod
    def transaction_id(self, ref):
        ...

    @staticmethod
    @abstractmethod
    def sn_product(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given Product
        """

    @staticmethod
    @abstractmethod
    def _create(*args, **kwargs):
        """
        A Method To Bulk-Create Product Objects
        """

    @staticmethod
    @abstractmethod
    def calculate_product_pv_amount(*args, **kwargs):
        """
        A Method To Calculate Total PV Amount Given To Product Group(Small Set Of SKU)
        """

    @staticmethod
    @abstractmethod
    def dict(*args, **kwargs) -> dict:
        """
        A Method To Dictify The Given Object
        """


# Payment


class Payment:
    pg_setting_info: dict
    init_pg_amount: Decimal
    curr_pg_amount: Decimal
    payment_method: dict
    payment_proceeding_result: dict
    outstandings: str

    @property
    @abstractmethod
    def transaction(self):
        ...

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @property
    @abstractmethod
    def orders(self):
        ...

    @property
    @abstractmethod
    def point_units(self):
        ...

    @property
    @abstractmethod
    def payment_refunds(self):
        ...

    @staticmethod
    @abstractmethod
    def sn_payment(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given Payment
        """

    @abstractmethod
    def get_payment_outstandings(self):
        """
        A Method To Get Payment Outstandings Which Is The Three Followings Combined:
            - Payment Gateway
            - Points
            - Coupons
        """

    @abstractmethod
    def set_payment_outstandings(self, points):
        """
        A Method To Set Payment Outstandings Which Is The Three Followings Combined:
            - Payment Gateway
            - Points
            - Coupons
        """

    @abstractmethod
    def get_cancelation_outstandings(self):
        """
        A Method To Get Cancelation Outstandings That The System Has To Get Returned To Client:
        """

    @abstractmethod
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
        """
        A Method To Set Partial Cancelation Outstandings That The System Has To Get Returned To Client
        Upon Cancelation Request On A Single SKU:
        """

    @abstractmethod
    def set_full_cancelation_outstandings(
        self, *, pg_refund_amount: Decimal, marketplace_user_data, note: str, **kwargs
    ):
        """
        A Method To Set Full Cancelation Outstandings That The System Has To Get Returned To Client
        Upon Cancelation Request On The Entire Order:
        """

    @abstractmethod
    def process_pg_complete_order_result(self, res, msg):
        ...

    @abstractmethod
    def deduct_point_units(self):
        """
        A Method To Deduct Point Amount From Point Units That A Client Used For The Given Order
        Upon Cancelation Request.
        """

    @abstractmethod
    def set_outstandings_on_point_request_fail(self, *, marketplace_user_data):
        """
        A Method To Fail Over Against Point Request Failure When In A Creation Of Order.
        """

    @abstractmethod
    def create_point_units(self):
        """
        A Method To Create Point Units After Successfully Making Point Use Request Against Point Partners
        """

    @abstractmethod
    def update_point_paid_amount_on_payment(self, *, marketplace_user_data, is_cart_order: bool, **kwargs):
        """
        A Method To Initialize Point Units After Successfully Making Point Use Request Against Point Partners
        """

    @abstractmethod
    def create_refund_logs(self):
        """
        A Method To Create Refund Payment Refund Logs After Cancelation Call.
        This May Create More Than One Refund Logs
        """

    @abstractmethod
    def set_confirm_date_on_sku_point(self, *, sku: Sku):
        """
        Method to update sku point to confirmed upon 'order-confirmed' event
        """

    @staticmethod
    @abstractmethod
    def dict(*args, **kwargs):
        """
        A Method To Dictify The Given Object
        """


@dataclass(eq=False)
class PaymentRefund:
    @staticmethod
    @abstractmethod
    def sn_payment_refund(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given PaymentRefund
        """


@dataclass(eq=False)
class PointUnit(PointBase):
    @property
    @abstractmethod
    def sku_id(self):
        ...

    @property
    @abstractmethod
    def transaction(self):
        ...

    @property
    @abstractmethod
    def transaction_id(self):
        ...

    @staticmethod
    @abstractmethod
    def sn_order_point_unit(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given Point Unit That Is Order-Specific
        """

    @staticmethod
    @abstractmethod
    def sn_sku_point_unit(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given Point Unit That Is Sku-Specific
        """

    @staticmethod
    @abstractmethod
    def update_disbursement_status(*args, **kwargs):
        """
        A Method To Update Point Unit
        """


@dataclass(eq=False)
class PaymentLog(Base):
    @staticmethod
    @abstractmethod
    def sn_payment_log(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given Payment Log
        """


# Enum


class BaseEnums:
    class ProductClass(str, Enum):
        TANGIBLE = "tangible"
        INTANGIBLE = "intangible"
        GIFTCARD = "giftcard"

    class TransactionStatus(str, Enum):
        PAYMENT_REQUIRED = "payment_required"
        PAYMENT_IN_PROGRESS = "payment_in_progress"
        PAID = "paid"
        FAILED = "failed"

    class Currency(str, Enum):
        KRW = "KRW"  # 원화
        USD = "UDS"  # 달러

    class InitiatorType(str, Enum):
        SUPPLIER = "supplier"  # 공급자
        CHANNEL_OWNER = "channel_owner"  # 채널 오너
        USER = "user"  # 고객
        SYSTEM = "system"


@dataclass
class Message:
    signature: str = field(init=False)

    def __post_init__(self):
        self.signature = self.__class__.__name__
        self.set_transaction_type()

    def set_transaction_type(self):
        transaction_id: str | None
        sku_id: str | None
        s_id: str | None
        if transaction_id := getattr(self, "transaction_id", None):
            if transaction_id.startswith("DT"):
                setattr(self, "transaction_type", "delivery")
            elif transaction_id.startswith("ST"):
                setattr(self, "transaction_type", "service")
        elif sku_id := getattr(self, "sku_id", None):
            if sku_id.startswith("OPS"):
                setattr(self, "transaction_type", "delivery")
            elif sku_id.startswith("SS"):
                setattr(self, "transaction_type", "service")
        elif sku_ids := getattr(self, "sku_ids", None):
            if s_id := next((s_id for s_id in sku_ids), None):
                if s_id.startswith("OPS"):
                    setattr(self, "transaction_type", "delivery")
                elif s_id.startswith("SS"):
                    setattr(self, "transaction_type", "service")

    def __hash__(self):
        return hash(self.signature)

    def __eq__(self, others):
        if not isinstance(others, Message):
            return False
        return self.signature == others.signature


event_registry = {}
command_registry = {}


def register_event(class_):
    event_registry[class_.__name__] = class_
    return class_


def register_command(class_):
    command_registry[class_.__name__] = class_
    return class_


def event_generator(event_type, **kwargs):
    if event_type not in event_registry:
        raise ValueError("Such Event Is Not Defined")
    try:
        event = event_registry[event_type](**kwargs)
    except Exception:
        raise WrongArgumentsForEvent("Wrong Values Are Given")
    else:
        return event
