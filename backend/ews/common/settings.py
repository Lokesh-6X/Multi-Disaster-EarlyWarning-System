"""Settings from `.env` (design/01 §1.7.3). Environment variables override the file.

Every process calls `load_settings()` once at start; a missing file or variable stops the process
with a message that names what is missing (start.ps1 step 1). Secrets never appear in `repr()` (NFR-08).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"

REQUIRED = [
    "DATABASE_URL",
    "MQTT_HOST", "MQTT_PORT", "MQTT_INGEST_USER", "MQTT_INGEST_PASSWORD",
    "SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_TLS",
    "APP_BASE_URL", "SECRET_KEY",
    "OPEN_METEO_FORECAST_URL", "OPEN_METEO_ARCHIVE_URL",
    "MODELS_DIR", "LOG_DIR", "LOG_LEVEL", "EWS_CLOCK",
]
# May be empty: SMTP without login (Mailpit), no dev origins, no demo database outside demo mode
OPTIONAL = ["SMTP_USER", "SMTP_PASSWORD", "DEV_ORIGINS", "DEMO_DATABASE_URL"]
ALL_VARIABLES = REQUIRED + OPTIONAL

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
CLOCK_MODES = {"real", "demo"}
_URL_PASSWORD = re.compile(r"(://[^:/@\s]+:)[^@\s]+@")


class SettingsError(RuntimeError):
    """Raised when `.env` is missing or invalid; the message says what to fix."""


def mask_url(url: str) -> str:
    """postgresql://ews:pw@host/db -> postgresql://ews:***@host/db"""
    return _URL_PASSWORD.sub(r"\1***@", url)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    demo_database_url: str = field(repr=False)
    mqtt_host: str
    mqtt_port: int
    mqtt_ingest_user: str
    mqtt_ingest_password: str = field(repr=False)
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str = field(repr=False)
    smtp_from: str
    smtp_tls: bool
    app_base_url: str
    dev_origins: list[str]
    secret_key: str = field(repr=False)
    open_meteo_forecast_url: str
    open_meteo_archive_url: str
    models_dir: Path
    log_dir: Path
    log_level: str
    clock_mode: str

    @property
    def active_database_url(self) -> str:
        """Demo mode runs against the separate demo database (design/11 §11.3.1)."""
        return self.demo_database_url if self.clock_mode == "demo" else self.database_url

    def __repr__(self) -> str:
        shown = [f"{f.name}={getattr(self, f.name)!r}" for f in fields(self) if f.repr]
        shown.insert(0, f"database_url={mask_url(self.database_url)!r}")
        if self.demo_database_url:
            shown.insert(1, f"demo_database_url={mask_url(self.demo_database_url)!r}")
        return f"Settings({', '.join(shown)})"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; `#` comments and blank lines ignored; surrounding quotes removed."""
    values: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SettingsError(f"{path}: line {number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings(env_file: Path | str | None = None) -> Settings:
    path = Path(env_file) if env_file else DEFAULT_ENV_FILE
    if not path.is_file():
        raise SettingsError(f".env not found at {path}. Copy .env.example to .env and fill in the passwords "
                            "(docs/setup-guide.md).")
    raw = read_env_file(path)
    raw.update({k: os.environ[k] for k in ALL_VARIABLES if k in os.environ})

    missing = [k for k in REQUIRED if not raw.get(k)]
    if missing:
        raise SettingsError(f"{path}: missing or empty: {', '.join(missing)} (see .env.example)")

    def integer(key: str) -> int:
        try:
            return int(raw[key])
        except ValueError:
            raise SettingsError(f"{key} must be a whole number, got {raw[key]!r}") from None

    def boolean(key: str) -> bool:
        value = raw[key].lower()
        if value not in {"true", "false", "1", "0", "yes", "no"}:
            raise SettingsError(f"{key} must be true or false, got {raw[key]!r}")
        return value in {"true", "1", "yes"}

    def choice(key: str, allowed: set[str], upper: bool = False) -> str:
        value = raw[key].upper() if upper else raw[key].lower()
        if value not in allowed:
            raise SettingsError(f"{key} must be one of {', '.join(sorted(allowed))}, got {raw[key]!r}")
        return value

    def directory(key: str) -> Path:
        p = Path(raw[key])
        return p if p.is_absolute() else path.parent / p

    clock_mode = choice("EWS_CLOCK", CLOCK_MODES)
    if clock_mode == "demo" and not raw.get("DEMO_DATABASE_URL"):
        raise SettingsError("EWS_CLOCK=demo needs DEMO_DATABASE_URL (the separate ews_demo database)")

    return Settings(
        database_url=raw["DATABASE_URL"],
        demo_database_url=raw.get("DEMO_DATABASE_URL", ""),
        mqtt_host=raw["MQTT_HOST"],
        mqtt_port=integer("MQTT_PORT"),
        mqtt_ingest_user=raw["MQTT_INGEST_USER"],
        mqtt_ingest_password=raw["MQTT_INGEST_PASSWORD"],
        smtp_host=raw["SMTP_HOST"],
        smtp_port=integer("SMTP_PORT"),
        smtp_user=raw.get("SMTP_USER", ""),
        smtp_password=raw.get("SMTP_PASSWORD", ""),
        smtp_from=raw["SMTP_FROM"],
        smtp_tls=boolean("SMTP_TLS"),
        app_base_url=raw["APP_BASE_URL"],
        dev_origins=[o.strip() for o in raw.get("DEV_ORIGINS", "").split(",") if o.strip()],
        secret_key=raw["SECRET_KEY"],
        open_meteo_forecast_url=raw["OPEN_METEO_FORECAST_URL"],
        open_meteo_archive_url=raw["OPEN_METEO_ARCHIVE_URL"],
        models_dir=directory("MODELS_DIR"),
        log_dir=directory("LOG_DIR"),
        log_level=choice("LOG_LEVEL", LOG_LEVELS, upper=True),
        clock_mode=clock_mode,
    )
