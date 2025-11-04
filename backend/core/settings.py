from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LOG_LEVEL: str = "INFO"
    LOG_RENDERER: str = "console"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
