from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LOG_LEVEL: str = "INFO"
    LOG_RENDERER: str = "console"
    REQUEST_ID_HEADER: str = "X-Request-ID"
    ENV: str = "dev"
    FIRST_SUPERUSER_EMAIL: str | None = None
    FIRST_SUPERUSER_PASSWORD: str | None = None
    FIRST_SUPERUSER_FULL_NAME: str | None = None

    # CORS settings
    CORS_ORIGINS: List[str] = ["*"]  # Comma-separated list of origins, or "*" for all
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = ["*"]  # Comma-separated list of methods, or "*" for all
    CORS_HEADERS: List[str] = ["*"]  # Comma-separated list of headers, or "*" for all

    # Database settings
    DATABASE_URL: str = "postgresql+asyncpg://aide:aide@db:5432/aide"

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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
