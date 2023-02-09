from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import WrongArgumentsForEvent

# from inspect import signature


@dataclass(repr=True, eq=False)
class Base(ABC):
    """
    Base Class For Domain Models
    """

    id: str = field(init=False)
    create_dt: datetime = field(init=False)
    update_dt: datetime = field(init=False)

    def _constructor(self) -> None:
        self._changes: deque = deque()

    @classmethod
    def constructor(cls):
        ag = object.__new__(cls)
        ag._constructor()
        return ag

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
    id: str = field(init=False, repr=False)
    create_dt: datetime = field(init=False, repr=False)
    update_dt: datetime = field(init=False, repr=False)
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


class Sku(Base):
    channel_name: str
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


@dataclass(eq=False)
class PaymentRefund:
    @staticmethod
    @abstractmethod
    def sn_payment_refund(*args, **kwargs):
        """
        A Method To Generate Serial Number Of The Given PaymentRefund
        """


@dataclass(eq=False)
class PointUnit:
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
