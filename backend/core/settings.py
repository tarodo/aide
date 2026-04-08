from typing import List, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_DEFAULT = "a_super_secret_key_that_should_be_in_env"
_MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    LOG_LEVEL: str = "INFO"
    LOG_RENDERER: str = "console"
    REQUEST_ID_HEADER: str = "X-Request-ID"
    ENV: str = "dev"
    FIRST_SUPERUSER_EMAIL: str | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_FULL_NAME: str | None = None

    # CORS settings
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = ["*"]
    CORS_HEADERS: List[str] = ["*"]

    # Database settings
    DATABASE_URL: str = "postgresql+asyncpg://aide:aide@db:5432/aide"

    # JWT settings
    JWT_SECRET_KEY: str = "a_super_secret_key_that_should_be_in_env"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    @staticmethod
    def _parse_list_or_wildcard(v: str | List[str]) -> List[str]:
        if isinstance(v, list):
            return v
        if v == "*":
            return ["*"]
        return [item.strip() for item in v.split(",")]

    @field_validator("CORS_ORIGINS", "CORS_METHODS", "CORS_HEADERS", mode="before")
    @classmethod
    def parse_cors_list(cls, v: str | List[str]) -> List[str]:
        return cls._parse_list_or_wildcard(v)

    @property
    def is_dev(self) -> bool:
        return self.ENV.lower() == "dev"

    @model_validator(mode="after")
    def _check_production_safety(self) -> Self:
        if self.is_dev:
            return self

        if (
            self.JWT_SECRET_KEY == _INSECURE_JWT_DEFAULT
            or len(self.JWT_SECRET_KEY) < _MIN_JWT_SECRET_LENGTH
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters and not the "
                "default value in non-dev environments. "
                "Generate one with: openssl rand -hex 32"
            )

        if "*" in self.CORS_ORIGINS and self.CORS_CREDENTIALS:
            raise ValueError(
                "CORS_ORIGINS='*' with CORS_CREDENTIALS=true is not allowed "
                "in non-dev environments. Set explicit origins."
            )

        return self

    # Keep raw env strings (e.g. CORS_ORIGINS=*) and parse them in validators.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", enable_decoding=False
    )


settings = Settings()
