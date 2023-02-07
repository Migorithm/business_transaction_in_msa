from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal, Protocol

from .base import Message, register_event


class Protocols:
    class AuthenticationMethod(Protocol):
        authentication_type: str
        membership_provider_name: str | None
        membership_user_identifiers: list | None

    class ExternalAuth(Protocol):
        external_auth_data: dict
        # "external_auth_data"
        #         {
        #             "IPIN_CI":"XXXX",
        #             "USER_ID":"xxxxx"
        #         }

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


@register_event
@dataclass(eq=False, slots=True)
class SkuUpdated(Message):
    sku_id: str
    user_id: str
    username: str
    initiator_type: str
    note: str | None
    attribute_options: dict | None = field(default_factory=dict)
    image_urls: dict | None = field(default_factory=dict)

    # Meta
    signature: str = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class OrderCreated(Message):
    marketplace_user_data: Protocols.DetailedUserData
    transaction_id: str
    transaction_type: Literal["service", "delivery"]
    point_processing_required: bool = False
    pg_processing_required: bool = False

    sku_status_to_change: str = "check_required"
    sku_ids: list[str] = field(default_factory=list)
    is_cart_order: bool = False

    # Meta
    signature: str = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class OrderCompleted(Message):
    def __post_init__(self):
        super(self.__class__, self).__post_init__()
        self.set_sku_status_to_change()

    marketplace_user_data: Protocols.DetailedUserData
    transaction_id: str

    delivery_sku_ids: set[str] = field(default_factory=set)
    sku_status_to_change: str = "check_required"
    inventory_change_option: bool = False  # False if it is to decrease inventory count
    is_cart_order: bool = False
    sku_id: str | None = None
    delete_option: str = "selected_all"
    transaction_type: Literal["service", "delivery"] = field(init=False)
    # Meta
    signature: str = field(init=False)

    def set_sku_status_to_change(self):
        if self.transaction_type == "delivery":
            self.sku_status_to_change = "check_required"
        elif self.transaction_type == "service":
            self.sku_status_to_change = "to_be_issued"


@register_event
@dataclass(eq=False, slots=True)
class PointUseRequestFailed(Message):
    transaction_id: str
    marketplace_user_data: Protocols.DetailedUserData
    delivery_sku_ids: set[str] = field(default_factory=set)
    pg_cancel_required: bool = False
    note: str = "system"
    sku_status_to_change = "payment_fail_point_error"
    transaction_type: Literal["service", "delivery"] = field(init=False)
    # Meta
    signature: str = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class OrderConfirmed(Message):
    sku_ids: set[str] = field(default_factory=set)  # order-finished skus
    is_auto: bool = False
    # Meta
    signature: str = field(init=False)

    transaction_type: Literal["service", "delivery"] = "delivery"


@register_event
@dataclass(eq=False, slots=True)
class PGPaymentCompleted(Message):
    transaction_id: str
    sku_status_to_change: str
    marketplace_user_data: Protocols.DetailedUserData

    sku_ids: list[str] = field(default_factory=list)
    point_processing_required: bool = False
    pg_processing_required: bool = False
    sku_id: str | None = None
    delete_option: str = "selected_all"
    is_cart_order: bool = False
    inventory_change_option: bool | None = None
    transaction_type: Literal["service", "delivery"] = field(init=False)
    # Meta
    signature: str = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class PGPaymentFailed(Message):
    transaction_id: str
    sku_status_to_change: str
    marketplace_user_data: Protocols.DetailedUserData
    transaction_type: Literal["service", "delivery"] = field(init=False)


# Backoffice
@register_event
@dataclass(eq=False, slots=True)
class DeliveryInvoiceReceived(Message):
    delivery_sku_ids: list = field(default_factory=list)
    carrier_info: set[tuple[str, str]] = field(default_factory=set)  # {(carrier_number, carrier_code)}
    first_registered_delivery_tracking_ids: set[str] = field(default_factory=set)
    # Meta
    signature: str = field(init=False)


# Market Place Cancelation
@register_event
@dataclass(eq=False, slots=True)
class OrderCancelRequested(Message):
    note: str
    transaction_id: str
    order_id: str
    point_cancel_required: bool
    pg_refund_amount: Decimal
    pg_cancel_required: bool
    refund_context: str
    marketplace_user_data: Protocols.DetailedUserData
    point_refund_amount: Decimal = Decimal("0")
    sku_ids_for_cancelation: set[str] = field(default_factory=set)

    # Meta
    signature: str = field(init=False)
    transaction_type: Literal["service", "delivery"] = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class PartialOrderCancelRequested(Message):
    marketplace_user_data: Protocols.DetailedUserData
    transaction_id: str
    order_id: str
    sku_id_for_cancelation: str
    note: str
    pg_refund_amount: Decimal
    refund_context: str
    pg_cancel_required: bool
    point_cancel_required: bool
    point_refund_amount: Decimal = Decimal("0")
    transaction_type: Literal["service", "delivery"] = field(init=False)

    initiator_type: str = field(init=False)

    # Meta
    signature: str = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class OrderCancelCompleted(Message):
    user_id: str
    transaction_id: str
    partial: bool
    refund_context: str
    username: str | None = None
    note: str | None = None
    pg_refund_amount: Decimal = Decimal("0")
    point_refund_amount: Decimal = Decimal("0")
    sku_ids_for_cancelation: set = field(default_factory=set)
    inventory_change_option: bool | None = None
    initiator_type: str = "user"

    # Meta
    signature: str = field(init=False)
    transaction_type: Literal["service", "delivery"] = field(init=False)


@register_event
@dataclass(eq=False, slots=True)
class ThreeDaysAheadOfOrderConfirmation(Message):
    sku_ids: set = field(default_factory=set)
    transaction_type: Literal["service", "delivery"] = field(init=False)


# Don't ever cross this line !


# Except for updating this enum!
class EventType(str, Enum):
    SKU_UPDATED = SkuUpdated.__name__
    ORDER_CANCEL_REQUESTED = OrderCancelRequested.__name__
    PARTIAL_ODER_CANCEL_REQUESTED = PartialOrderCancelRequested.__name__
    ORDER_CREATED = OrderCreated.__name__
    TRANSACTION_COMPLETED = OrderCompleted.__name__
    POINT_USE_REQUEST_FAILED = PointUseRequestFailed.__name__
    ORDER_CONFIRMED = OrderConfirmed.__name__
    THREE_DAYS_AHEAD_OF_ORDER_CONFIRMATION = ThreeDaysAheadOfOrderConfirmation.__name__
    PG_PAYMENT_COMPLETED = PGPaymentCompleted.__name__
    PG_PAYMENT_FAILED = PGPaymentFailed.__name__
    DELIVERY_INVOICE_RECEIVED = DeliveryInvoiceReceived.__name__
    ORDER_CANCEL_COMPLETED = OrderCancelCompleted.__name__
