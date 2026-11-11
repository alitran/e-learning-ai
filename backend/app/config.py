from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "mysql+asyncmy://elearning:elearning@127.0.0.1:3306/elearning_ai?charset=utf8mb4"
    app_secret_key: str = "dev-secret-change-this-before-deployment"
    access_token_expire_minutes: int = 10080
    upload_dir: Path = Path("data/uploads")
    max_upload_mb: int = 20
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    app_base_url: str = "http://localhost:8080"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore", case_sensitive=False)


settings = Settings()
