"""Process configuration read from environment variables.

Provisional scaffold written for M1 development (scaffold owner: D). It is kept
dependency-free so the shared scaffold can replace the loader later.
"""

import os
from dataclasses import dataclass

AUTH_MODES = ("disabled", "dev-headers")


@dataclass(frozen=True)
class AppConfig:
    database_url: str
    business_timezone: str = "Asia/Shanghai"
    # "disabled": every protected endpoint answers 401 until C's auth lands.
    # "dev-headers": trust X-Dev-* headers; local development and tests only.
    auth_mode: str = "disabled"
    checkin_code_secret: str = ""

    def __post_init__(self) -> None:
        if self.auth_mode not in AUTH_MODES:
            raise ValueError(f"AUTH_MODE must be one of {AUTH_MODES}, got {self.auth_mode!r}")


def load_config() -> AppConfig:
    return AppConfig(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+psycopg://campus:campus@127.0.0.1:5432/campus"
        ),
        business_timezone=os.environ.get("BUSINESS_TIMEZONE", "Asia/Shanghai"),
        auth_mode=os.environ.get("AUTH_MODE", "disabled"),
        checkin_code_secret=os.environ.get("M1_CHECKIN_CODE_SECRET", ""),
    )
