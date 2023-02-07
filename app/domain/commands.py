from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Literal, Protocol

from .base import Message, register_command


class Protocols:
    class ReceiverAddress(Protocol):
        main: str
        extra: str
        postal_code: str
        region_id: str | None

    class ShippingInfo(Protocol):
        sender_name: str
        sender_phone: str
        sender_email: str
        delivery_note: str
        receiver_name: str
        receiver_phones: str
        receiver_address: Protocols.ReceiverAddress
        postal_code: str | None

    class PgSettingInfo(Protocol):
        iv: str
        mid: str
        pg_type: str
        signkey: str
        pc_order_fail_url: str
        pc_order_success_url: str
        mobile_order_fail_url: str
        mobile_order_success_url: str
        iniapi_key: str | None
        smartro_cancel_pw: str | None

    class PointSettingInfo(Protocol):
        provider_name: str
        provider_code: str
        conversion_ratio: int
        credential: dict | None
        request_info: dict | None
        type: str | None
        priority: str
        point_unit_type: str

    class ChannelInfo(Protocol):
        pg_setting_info: Protocols.PgSettingInfo
        point_setting_info: list[Protocols.PointSettingInfo]
        country: str
        settlement_frequency: int

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

    class PtIn(Protocol):
        point_provider_name: str
        point_provider_code: str
        external_user_id: str | None
        requested_point_amount: Decimal
        type: str
        priority: int | None
        sku_id: str | None
        conversion_ratio: Decimal = Decimal("1")


@register_command
@dataclass(eq=False, slots=True)
class RequestClaim(Message):
    delivery_sku_id: str
    user_id: str
    username: str
    update_context: str
    note: str | None = None
    attribute_options: dict | None = field(default_factory=dict)
    image_urls: dict | None = field(default_factory=dict)
    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class CreateOrder(Message):
    channel_info: Protocols.ChannelInfo
    marketplace_user_data: Protocols.DetailedUserData

    delivery_products_to_order: list[dict] = field(default_factory=list)
    shipping_info: Protocols.ShippingInfo | None = None

    service_products_to_order: list[dict] = field(default_factory=list)
    sellable_sku_qty_mapper: dict = field(default_factory=dict)

    anonymous_user_password: str | None = None
    currency: str = "KRW"
    is_cart_order: bool = False
    web_url: str = ""

    postal_code: str | None = field(default=None)

    point_units: list[Protocols.PtIn] = field(default_factory=list)
    payment_method: dict = field(default_factory=dict)

    # Meta
    signature: str = field(init=False)
    transaction_type: Literal["delivery", "service"] = field(default="delivery")


@register_command
@dataclass(eq=False, slots=True)
class CancelOrder(Message):  # MP
    marketplace_user_data: Protocols.DetailedUserData
    transaction_id: str
    note: str = ""
    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class CancelOrderPartially(Message):  # MP
    marketplace_user_data: Protocols.DetailedUserData
    refund_context: str
    sku_id: str
    note: str = ""

    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class ConfirmOrder(Message):
    sku_id: str | None = None
    order_confirmation_deadline: int | str = 7
    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class CompletePg(Message):
    marketplace_user_data: Protocols.DetailedUserData
    transaction_id: str
    is_cart_order: bool = False
    web_url: str | None = None
    log: dict = field(default_factory=dict)  # proceeding result
    # Meta
    transaction_type: Literal["service", "delivery"] = "delivery"
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class UpdateCarrierInfo(Message):
    portal_id: str
    user_id: str
    delivery_sku_id: str
    carrier_code: str
    carrier_number: str
    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class CancelPartiallyOnClaim(Message):
    initiator_id: str
    portal_id: str
    delivery_sku_id: str
    refund_context: str
    is_applied_delivery_fee_exclusion: bool = False

    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class ReceiveDeliveryInvoice(Message):
    supplier_user_id: str
    supplier_portal_id: str
    shipping_invoice_data: dict = field(default_factory=dict)
    shipping_requested_sku_ids: list[str] = field(default_factory=list)

    # Meta
    signature: str = field(init=False)


@register_command
@dataclass(eq=False, slots=True)
class TrackDeliveryOnCallback(Message):
    delivery_tracking_id: str
    carrier_code: str
    carrier_number: str
    tracking_detail: dict = field(default_factory=dict)


@register_command
@dataclass(eq=False, slots=True)
class ChangeDeliveryInvoice(Message):
    carrier_code: str
    carrier_number: str
    delivery_sku_id: str
    user_id: str
    portal_id: str


# SupplyService
@register_command
@dataclass(eq=False, slots=True)
class ChangeSkuStatusOnSupplierAction(Message):
    supplier_user_id: str
    supplier_portal_id: str
    delivery_sku_info: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    """{
        delivery_sku_id : tuple[target_status,note]
    }"""


# Backoffice CS
@register_command
@dataclass(eq=False, slots=True)
class ChangeSkuStatusOnClaimCheck(Message):
    target_status: str
    delivery_sku_id: str
    note: str

    user_id: str
    reason_for_action: str | None = None
    refund_delivery_fee_method: str = "default"
    exchange_delivery_fee_method: str = "default"


class CommandType(str, Enum):
    REQUEST_CLAIM = RequestClaim.__name__
    CREATE_ORDER = CreateOrder.__name__
    CANCEL_ORDER = CancelOrder.__name__
    CANCEL_ORDER_PARTIALLY = CancelOrderPartially.__name__
    CONFIRM_ORDER = ConfirmOrder.__name__
    COMPLETE_PG = CompletePg.__name__
    UPDATE_CARRIER_INFO = UpdateCarrierInfo.__name__
    CANCEL_PARTIALLY_ON_CLAIM = CancelPartiallyOnClaim.__name__
    RECEIVE_DELIVERY_INVOICE = ReceiveDeliveryInvoice.__name__
    TRACK_DELIVERY_ON_CALLBACK = TrackDeliveryOnCallback.__name__
