"""
Application configuration using Pydantic Settings
"""
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, field_validator, model_validator

# Resolve the project-level data directory regardless of CWD.
# config.py lives at  <project>/backend/app/config.py  → data is at <project>/data/
_DATA_DIR = str(Path(__file__).resolve().parent.parent.parent / "data")


class Settings(BaseSettings):
    """Application settings"""
    
    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Unihockey Stats"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str | AnyHttpUrl] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str] | str:
        """Parse CORS origins from string or list"""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list,)):
            return v
        raise ValueError(v)
    
    # SwissUnihockey API
    SWISSUNIHOCKEY_API_URL: str = "https://api-v2.swissunihockey.ch"
    SWISSUNIHOCKEY_LOCALE: str = "de-CH"
    SWISSUNIHOCKEY_CACHE_ENABLED: bool = True
    SWISSUNIHOCKEY_CACHE_DIR: str = str(Path(_DATA_DIR) / "cache")
    
    # Redis (Optional)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    
    # Database (Optional)
    DATABASE_URL: str | None = None
    DATABASE_PATH: str = str(Path(_DATA_DIR) / "swissunihockey.db")
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # Admin protection
    ADMIN_PIN: str = "1234"          # Override via env: ADMIN_PIN=yourpin
    SESSION_SECRET: str = "change-me-in-production-use-random-32-chars"

    # Contact form email (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    CONTACT_EMAIL: str = ""          # Recipient address for contact form submissions

    _INSECURE_SECRET = "change-me-in-production-use-random-32-chars"
    _INSECURE_PIN    = "1234"

    @model_validator(mode="after")
    def check_production_secrets(self) -> "Settings":
        if not self.DEBUG:
            if self.SESSION_SECRET == self._INSECURE_SECRET:
                raise ValueError(
                    "SESSION_SECRET must be changed from the default in production. "
                    "Set the SESSION_SECRET environment variable to a random 32+ character string."
                )
            if self.ADMIN_PIN == self._INSECURE_PIN:
                raise ValueError(
                    "ADMIN_PIN must be changed from the default '1234' in production. "
                    "Set the ADMIN_PIN environment variable."
                )
        return self

    model_config = SettingsConfigDict(
        # Absolute path so .env is found regardless of the CWD uvicorn is run from.
        # Locally: backend/app/config.py → parent.parent = backend/ → backend/.env
        # Docker:  /app/app/config.py    → parent.parent = /app/    → /app/.env
        env_file=str(Path(__file__).parent.parent / ".env"),
        case_sensitive=True,
    )


# Global settings instance
settings = Settings()
