"""Application configuration — รับค่าจาก environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ตั้งค่าหลักของแอปพลิเคชัน อ่านจาก .env หรือ environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Accounting SaaS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Server ───────────────────────────────────────────────────────────────
    PORT: int = 8000  # Railway inject PORT อัตโนมัติ

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = ""  # ถ้าว่างจะ build จาก DATA_DIR ใน get_platform_db_url
    # production: postgresql+asyncpg://user:pass@host:5432/dbname
    DB_ECHO: bool = False  # log SQL statements

    # ── Data directory ────────────────────────────────────────────────────────
    # Railway: /app/data (mount volume ที่นี่)
    # Local dev: ตั้ง DATA_DIR=data ใน .env หรือปล่อยให้ใช้ /app/data
    DATA_DIR: Path = Path("/app/data")

    # ── Anthropic / OCR ───────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    OCR_MODEL: str = "claude-sonnet-4-6"
    OCR_MAX_TOKENS: int = 4096
    OCR_MAX_IMAGE_SIZE_MB: float = 5.0

    # ── Email (optional) ─────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@accounting.local"

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # ── Pagination ───────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 500

    # ── Thai fiscal year ─────────────────────────────────────────────────────
    FISCAL_YEAR_START_MONTH: int = 1  # มกราคม (ปีปฏิทิน)

    @field_validator("DATA_DIR", mode="before")
    @classmethod
    def create_data_dir(cls, v: str | Path) -> Path:
        path = Path(v)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_platform_db_url(self) -> str:
        """คืน DATABASE_URL สำหรับ platform (shared.sqlite)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        db_path = self.DATA_DIR / "shared.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    def get_company_db_url(self, firm_id: int, company_id: int) -> str:
        """คืน DATABASE_URL สำหรับ company เฉพาะ."""
        db_path = self.DATA_DIR / f"firm_{firm_id}" / f"company_{company_id}" / "db.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    def get_firm_shared_db_url(self, firm_id: int) -> str:
        """คืน DATABASE_URL สำหรับ shared tables ของ firm."""
        db_path = self.DATA_DIR / f"firm_{firm_id}" / "shared.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"


@lru_cache
def get_settings() -> Settings:
    """คืน Settings instance (cached singleton)."""
    return Settings()


settings = get_settings()
