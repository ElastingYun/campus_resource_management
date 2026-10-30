from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
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
    c_enabled: bool = False
    c_config_file: Path | None = None
    resources_service_token: SecretStr | None = Field(default=None, min_length=1)
    m1_service_token: SecretStr | None = Field(default=None, min_length=1)

    @field_validator("c_config_file", "resources_service_token", "m1_service_token", mode="before")
    @classmethod
    def empty_optional_policy_path(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def c_requires_explicit_configuration(self):
        if self.c_enabled and (self.c_config_file is None or not self.database_configured):
            raise ValueError(
                "C component requires a policy file and complete database configuration"
            )
        return self

    @property
    def database_configured(self) -> bool:
        return self.db_host is not None and self.db_password is not None
