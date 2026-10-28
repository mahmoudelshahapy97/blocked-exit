"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import api_router
from app.core.config import settings
from app.core.database import dispose_engine, init_models
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.observability import RequestIdMiddleware
from app.services import alerting, camera_health, model_loader, retention
from app.services.audit import AuditMiddleware
from app.services.stream_manager import stream_manager
from app.utils.video import configure_ffmpeg_transport

STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = get_logger(__name__)

DESCRIPTION = """
Real-time emergency-exit blockage detection.

Two interchangeable detection strategies:

* **zone_based** — YOLO11 detects obstacles; whatever overlaps the configured
  door polygon reduces the accessible area. Works with pretrained COCO weights.
* **door_centric** — a door-only detector reports the visible door and compares
  it against a stored unobstructed reference, so unseen obstacle types are
  handled without retraining (ICAART 2026, Talebi et al.).

Every verdict reports *how accessible* the exit is, what is blocking it, for how
long, and the resulting risk — not just a boolean.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    configure_ffmpeg_transport()
    logger.info("Starting %s v%s (%s)", settings.APP_NAME, __version__, settings.ENV)

    settings.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    settings.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    if settings.AUTO_CREATE_TABLES:
        try:
            await init_models()
        except Exception as exc:
            logger.error("Database initialisation failed: %s", exc)

    status = model_loader.preload()
    logger.info("Model availability: %s", status)

    await stream_manager.startup()
    await retention.startup()
    camera_health.start()
    try:
        yield
    finally:
        await camera_health.stop()
        await retention.shutdown()
        await stream_manager.shutdown()
        await alerting.close_http_client()
        await dispose_engine()
        logger.info("Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    description=DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # False when origins is "*": browsers reject that pairing outright.
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outermost last: the request id exists before anything logs or audits.
app.add_middleware(AuditMiddleware, api_prefix=settings.API_V1_PREFIX)
app.add_middleware(RequestIdMiddleware)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)

if settings.ENABLE_ZONE_EDITOR and STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Docs when they are enabled, otherwise the zone editor, otherwise health."""
    if settings.docs_enabled:
        return RedirectResponse(url="/docs")
    if settings.ENABLE_ZONE_EDITOR and STATIC_DIR.is_dir():
        return RedirectResponse(url="/ui/zone-editor.html")
    return RedirectResponse(url=f"{settings.API_V1_PREFIX}/health")
