from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Notary Everyday ID Verify AI"
    version: str = "1.0.0"
    upload_dir: str = "backend/uploads"
    expiring_soon_days: int = 30
    max_upload_mb: int = 10
    allowed_origins: list[str] = ["*"]
    enable_easyocr: bool = True
    enable_paddleocr: bool = False  # Turn on after installing paddle stack if desired.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
