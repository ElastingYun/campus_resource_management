"""M1 configuration from CAMPUS_M1_* environment variables (or the repository's .env)."""

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class M1Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAMPUS_M1_",
        env_file=Path(__file__).resolve().parents[4] / ".env",
        extra="ignore",
    )

    # Business timezone for whole-hour slots, opening hours and daily check-in codes.
    timezone: str = "Asia/Shanghai"
    # "disabled": every protected endpoint answers 401 until C's authentication lands.
    # "dev-headers": trust X-Dev-* headers; local development and tests only.
    auth_mode: Literal["disabled", "dev-headers"] = "disabled"
    # Derives each room's daily check-in code; check-in answers 503 while unset.
    checkin_code_secret: SecretStr | None = Field(default=None, min_length=1)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    def checkin_secret(self) -> str:
        return self.checkin_code_secret.get_secret_value() if self.checkin_code_secret else ""
