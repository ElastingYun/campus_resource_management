from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CAMPUS_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )

    db_host: str | None = Field(default=None, min_length=1)
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = Field(default="campus", min_length=1)
    db_user: str = Field(default="campus", min_length=1)
    db_password: SecretStr | None = Field(default=None, min_length=1)

    @property
    def database_configured(self) -> bool:
        return self.db_host is not None and self.db_password is not None
