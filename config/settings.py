from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "check"
    DEBUG: bool = False

    JWT_SECRET_KEY: str = "488d6ec912316b84a725cfbc65aafe5fde1f8b6bfbf595c030a2c806ac7bd9f2"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    FIREBASE_SERVICE_ACCOUNT_PATH: str = "./firebase-adminsdk.json"
    MAX_UPLOAD_SIZE_MB: int = 10

    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    GEMINI_API_KEY: str

settings = Settings()
