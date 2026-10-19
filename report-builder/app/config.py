"""All settings come from environment variables (.env file). No secrets in code."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None or value == "" else value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number, got '{raw}'")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got '{raw}'")


class Settings:
    def __init__(self) -> None:
        self.api_key = os.getenv("API_KEY", "").strip()
        self.currency_code = os.getenv("CURRENCY_CODE", "INR").strip().upper() or "INR"

        data_dir = BASE_DIR / "data"
        self.data_dir = data_dir
        self.reports_dir = data_dir / "reports"
        self.database_url = os.getenv("DATABASE_URL", "").strip() or f"sqlite:///{(data_dir / 'app.db').as_posix()}"

        self.max_upload_bytes = _int("MAX_UPLOAD_MB", 10) * 1024 * 1024
        self.max_rows = _int("MAX_ROWS", 100_000)
        self.max_cols = 60
        self.max_invalid_ratio = _float("MAX_INVALID_RATIO", 0.3)
        self.date_dayfirst = _bool("DATE_DAYFIRST", True)

        self.ai_provider = os.getenv("AI_PROVIDER", "none").strip().lower()
        self.ai_api_key = os.getenv("AI_API_KEY", "").strip()
        self.ai_model = os.getenv("AI_MODEL", "").strip()

        self.schedule_enabled = _bool("SCHEDULE_ENABLED", False)
        self.schedule_day_of_week = os.getenv("SCHEDULE_DAY_OF_WEEK", "mon").strip()
        self.schedule_hour = _int("SCHEDULE_HOUR", 9)
        self.schedule_days_back = _int("SCHEDULE_DAYS_BACK", 7)

        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = _int("SMTP_PORT", 587)
        self.smtp_user = os.getenv("SMTP_USER", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", "").strip() or self.smtp_user
        self.report_email_to = [e.strip() for e in os.getenv("REPORT_EMAIL_TO", "").split(",") if e.strip()]

    def validate(self) -> None:
        """Fail fast at startup if the app is not safely configured."""
        if len(self.api_key) < 12:
            raise RuntimeError(
                "API_KEY is missing or too short (min 12 characters). "
                "Copy .env.example to .env and set API_KEY."
            )
        if not re.fullmatch(r"[A-Z]{3}", self.currency_code):
            raise RuntimeError("CURRENCY_CODE must be a three-letter ISO 4217 code, such as INR or USD")
        if self.ai_provider not in {"none", "anthropic", "gemini"}:
            raise RuntimeError("AI_PROVIDER must be one of: none, anthropic, gemini")
        if self.ai_provider != "none" and not self.ai_api_key:
            raise RuntimeError("AI_API_KEY is required when AI_PROVIDER is not 'none'")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
