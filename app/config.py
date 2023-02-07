import os

from pydantic import BaseSettings


class DeliverySettings(BaseSettings):
    SMART_DELIVERY_HOST = "http://sweettracker.net:8102"
    SMART_DELIVERY_TRACKING_STATUS_URL = "https://sweettracker.co.kr/api/v1/trackingInfo"
    SMART_DELIVERY_API_KEY = "test_key"
    SMART_DELIVERY_TIER = "testuser"
    SMART_DELIVERY_KEY = "testuser"


DELIVERY_SETTINGS = DeliverySettings()

TRX_EXTERNAL_URL: str = os.getenv("TRX_EXTERNAL_URL", "http://localhost:8000/external")  # TODO Set on secret manager
TZ: str = os.getenv("TZ", "UTC")
