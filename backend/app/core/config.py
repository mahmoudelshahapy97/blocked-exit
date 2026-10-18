"""Application settings, loaded once from the environment / .env file."""

from __future__ import annotations

import json
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

# COCO class ids that can plausibly obstruct an emergency exit.
DEFAULT_OBSTACLE_CLASSES = [
    0,  # person
    1,  # bicycle
    3,  # motorcycle
    13,  # bench
    24,  # backpack
    26,  # handbag
    28,  # suitcase
    56,  # chair
    57,  # couch
    58,  # potted plant
    59,  # bed
    60,  # dining table
    62,  # tv
    63,  # laptop
    72,  # refrigerator
]


# The published development signing key. Named so `_guard_production` can
# recognise it; see the SECRET_KEY field below.
DEV_SECRET_KEY = "dev-only-insecure-secret-change-me"


def _parse_list(value: str) -> list:
    """Turn an env string into a list, accepting `a,b,c` or a JSON array.

    `NoDecode` on these fields means pydantic-settings hands us the raw string
    and does no JSON parsing of its own — so if we do not decode the bracketed
    form here, nothing does, and the documented JSON syntax silently fails
    validation.
    """
    stripped = value.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"expected a JSON array or a comma-separated list: {exc}"
            ) from exc
        if not isinstance(decoded, list):
            raise ValueError("expected a JSON array")
        return decoded
    return [item.strip() for item in stripped.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    APP_NAME: str = "InsightEye Blocked Exit Detection"
    ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    # NoDecode: parse these ourselves so plain `a,b,c` works in .env
    # (pydantic-settings would otherwise insist on JSON).
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    # Interactive docs expose every route and schema; off by default in production.
    ENABLE_DOCS: bool | None = None
    # Browser page for drawing the exit region (/ui/zone-editor.html).
    ENABLE_ZONE_EDITOR: bool = True

    # --- Authentication --------------------------------------------------
    # Signing key for every JWT this service issues. The development default is
    # a literal, published string: it is here so `docker compose up` works out
    # of the box, and the production guard below refuses to start with it.
    SECRET_KEY: str = DEV_SECRET_KEY
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Like the platform, accounts are created by a superadmin. The very first
    # signup is always accepted and becomes that superadmin; with this on, later
    # signups are accepted too and join the shared "Default Workspace" as members.
    ALLOW_OPEN_SIGNUP: bool = False
    # Revoked-token rows are only useful until the token would have expired
    # anyway; the retention sweep drops them after that.
    TOKEN_CLEANUP_ENABLED: bool = True

    # --- Database --------------------------------------------------------
    DATABASE_URL: str = (
        "postgresql+asyncpg://insighteye:insighteye@localhost:5432/blocked_exit"
    )
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False
    AUTO_CREATE_TABLES: bool = True  # dev convenience; use alembic in production

    # --- Models ----------------------------------------------------------
    MODEL_DIR: Path = BASE_DIR / "models"
    MODEL_PATH: str = "yolo11n.pt"
    SEG_MODEL_PATH: str = "yolo26n-seg.pt"
    DOOR_MODEL_PATH: str | None = None  # e.g. "door_yolo11s.pt" once trained
    DEVICE: str = "cpu"
    CONF_THRESHOLD: float = 0.35
    IOU_THRESHOLD: float = 0.5
    IMG_SIZE: int = 640
    USE_SEGMENTATION: bool = True
    OBSTACLE_CLASSES: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_OBSTACLE_CLASSES)
    )
    DOOR_CLASS_NAME: str = "door"

    # --- Strategy --------------------------------------------------------
    DEFAULT_STRATEGY: str = "zone_based"
    TRACKER: str = "bytetrack.yaml"
    ENABLE_TRACKING: bool = True
    # Door-centric answers "how much door is visible" but never names the
    # obstacle. Run the zone-based detector alongside it purely for the
    # human-readable "blocked by ..." list.
    DOOR_CENTRIC_EXPLAIN: bool = True

    # --- Blockage thresholds (percent of exit still accessible) ----------
    CLEAR_MIN_PCT: float = 85.0  # >= this => CLEAR
    FULL_MAX_PCT: float = 40.0  # <  this => FULL, otherwise PARTIAL

    # --- Temporal filtering ---------------------------------------------
    CONFIRM_SECONDS: float = 5.0
    CLEAR_SECONDS: float = 3.0
    PROCESS_FPS: float = 5.0

    # --- Streaming -------------------------------------------------------
    RTSP_TRANSPORT: str = "tcp"
    STREAM_READ_TIMEOUT_S: float = 15.0
    STREAM_RECONNECT_BASE_S: float = 1.0
    STREAM_RECONNECT_MAX_S: float = 30.0
    LOOP_VIDEO_FILES: bool = True  # replay local files forever (testing)
    SNAPSHOT_DIR: Path = BASE_DIR / "data" / "snapshots"
    JPEG_QUALITY: int = 85
    # Every MJPEG viewer costs a JPEG encode per frame; cap concurrent viewers
    # so a few forgotten browser tabs cannot starve the detection pipeline.
    MAX_MJPEG_CLIENTS: int = 8
    # "Test connection": how long one probe may take to open the source and
    # read a frame, and how many sources may be probed at once (probe-all
    # must not open every camera in the workspace simultaneously).
    PROBE_TIMEOUT_S: float = 8.0
    PROBE_CONCURRENCY: int = 4

    # --- Reporting -------------------------------------------------------
    # Days and hours in reports, filters and charts are local to this zone
    # (the platform reports in Africa/Cairo). Storage stays UTC.
    REPORT_TIMEZONE: str = "Africa/Cairo"

    # --- Worker supervision ----------------------------------------------
    WORKER_SUPERVISION_ENABLED: bool = True
    WORKER_SUPERVISION_INTERVAL_S: float = 15.0
    WORKER_RESTART_BACKOFF_BASE_S: float = 5.0
    WORKER_RESTART_BACKOFF_MAX_S: float = 300.0

    # --- Retention -------------------------------------------------------
    RETENTION_ENABLED: bool = True
    RETENTION_INTERVAL_S: float = 21600.0  # 6 hours
    EVENT_RETENTION_DAYS: int = 90
    ALERT_RETENTION_DAYS: int = 90
    SNAPSHOT_RETENTION_DAYS: int = 30
    SNAPSHOT_MAX_TOTAL_MB: int = 2048

    # --- Alerting --------------------------------------------------------
    ALERTS_ENABLED: bool = True
    ALERT_MIN_DURATION_S: float = 10.0
    ALERT_COOLDOWN_S: float = 300.0
    WEBHOOK_URL: str | None = None
    WEBHOOK_TIMEOUT_S: float = 10.0
    WEBHOOK_RETRIES: int = 2  # retries after the first attempt
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    ALERT_EMAIL_FROM: str | None = None
    ALERT_EMAIL_TO: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Risk scoring weights -------------------------------------------
    RISK_W_ACCESSIBILITY: float = 0.45
    RISK_W_DURATION: float = 0.30
    RISK_W_PEOPLE: float = 0.15
    RISK_W_CLASS: float = 0.10
    RISK_DURATION_SATURATION_S: float = 120.0

    @field_validator("CORS_ORIGINS", "ALERT_EMAIL_TO", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept `a,b,c` from .env as well as a JSON list."""
        if isinstance(value, str):
            return _parse_list(value)
        return value

    @field_validator("OBSTACLE_CLASSES", mode="before")
    @classmethod
    def _split_int_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in _parse_list(value)]
        return value

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        """Refuse to start production with settings that are only safe in dev.

        These two default to on for local convenience and are genuinely
        dangerous in production: `AUTO_CREATE_TABLES` lets the app mutate the
        schema out from under Alembic, and `DEBUG` changes error verbosity.
        Both fail loudly here rather than quietly at 3am. Everything else is a
        warning — an operator may have good reasons, and refusing to boot over
        a CORS setting would be worse than the setting.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.SECRET_KEY == DEV_SECRET_KEY:
            problems.append(
                "SECRET_KEY is still the development default, which is public "
                "in app/core/config.py — anyone could mint themselves an admin "
                "token. Set it to a random 32+ byte value "
                "(`python -c 'import secrets; print(secrets.token_urlsafe(48))'`)"
            )
        elif len(self.SECRET_KEY) < 32:
            problems.append(
                f"SECRET_KEY is only {len(self.SECRET_KEY)} characters — use at "
                "least 32 so HS256 signatures are not brute-forceable"
            )
        if self.AUTO_CREATE_TABLES:
            problems.append(
                "AUTO_CREATE_TABLES=true — set it false and run "
                "`alembic upgrade head` so migrations own the schema"
            )
        if self.DEBUG:
            problems.append("DEBUG=true — set it false")
        if problems:
            raise ValueError(
                "Refusing to start with ENV=production and: " + "; ".join(problems)
            )

        if self.CORS_ORIGINS == ["*"]:
            warnings.warn(
                "ENV=production with CORS_ORIGINS=* — any site can call this API "
                "from a browser. Set an explicit origin list.",
                stacklevel=2,
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.ENV.strip().lower() in {"production", "prod"}

    @property
    def docs_enabled(self) -> bool:
        """Explicit ENABLE_DOCS wins; otherwise docs are on outside production."""
        if self.ENABLE_DOCS is not None:
            return self.ENABLE_DOCS
        return not self.is_production

    @property
    def cors_allow_credentials(self) -> bool:
        """Wildcard origins and credentials are mutually exclusive.

        Browsers reject `Access-Control-Allow-Origin: *` on a credentialed
        request, so advertising both produces requests that fail in the client
        rather than the permissive setup it looks like.
        """
        return "*" not in self.CORS_ORIGINS

    @property
    def process_interval_s(self) -> float:
        return 1.0 / self.PROCESS_FPS if self.PROCESS_FPS > 0 else 0.0

    def resolve_model(self, name: str | None) -> str | None:
        """Resolve a weights name to a concrete path under MODEL_DIR.

        Returning the full path (rather than the bare name) matters for weights
        that do not exist yet: ultralytics downloads official checkpoints to the
        path it is given, so they land in MODEL_DIR instead of the working
        directory and are reused on the next start.
        """
        if not name:
            return None
        candidate = Path(name)
        if candidate.is_absolute():
            return str(candidate)
        if candidate.exists():
            return str(candidate.resolve())
        return str(self.MODEL_DIR / name)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
