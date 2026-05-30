from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
import json

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
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    FIREBASE_SERVICE_ACCOUNT_PATH: str = str(BASE_DIR / "firebase-adminsdk.json")
    FIREBASE_SERVICE_ACCOUNT_JSON: str | None = None
    MAX_UPLOAD_SIZE_MB: int = 10

    ALLOWED_ORIGINS: str | list[str] = [
        "http://localhost:5137",
        "https://checkapk.vercel.app",
    ]
    @field_validator("ALLOWED_ORIGINS", mode="before")
    def _parse_allowed_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            # Accept JSON array or comma-separated string
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    inner = v[1:-1].strip()
                    if not inner:
                        return []
                    return [item.strip() for item in inner.split(",") if item.strip()]
            return [item.strip() for item in v.split(",") if item.strip()]
        return v
    GEMINI_API_KEY: str

settings = Settings()
