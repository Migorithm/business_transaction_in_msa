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


class PersistentDB(BaseSettings):
    POSTGRES_SERVER: str = ""
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    POSTGRES_PORT: str = ""
    POSTGRES_PROTOCOL: str = ""

    def get_uri(self):
        return "{}://{}:{}@{}:{}/{}".format(
            self.POSTGRES_PROTOCOL,
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.POSTGRES_SERVER,
            self.POSTGRES_PORT,
            self.POSTGRES_DB,
        )

    @property
    def test_db(self):
        return f"{self.POSTGRES_DB}_test"

    def get_test_uri(self):
        return "{}://{}:{}@{}:{}/{}".format(
            self.POSTGRES_PROTOCOL,
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.POSTGRES_SERVER,
            self.POSTGRES_PORT,
            self.test_db,
        )


PERSISTENT_DB = PersistentDB()
