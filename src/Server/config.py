from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    influxdb_url: str = os.getenv("INFLUXDB_URL")
    influxdb_token: str = os.getenv("INFLUXDB_TOKEN")
    influxdb_org: str = os.getenv("INFLUXDB_ORG")
    influxdb_bucket: str = os.getenv("INFLUXDB_BUCKET")
    secret_key: str = os.getenv("SECRET_KEY")
    signup_sec_key: str = os.getenv("SIGNUP_SEC_KEY")


settings = Settings()
