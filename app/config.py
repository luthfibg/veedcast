from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Veedcast"
    environment: str = "development"
    admin_password: str = "change-me"
    database_url: str = "sqlite:///./veedcast.db"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()