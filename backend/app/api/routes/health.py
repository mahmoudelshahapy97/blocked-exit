"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import ManagerDep
from app.core.config import settings
from app.core.database import check_database
from app.services import model_loader
from app.services.detector import registry
from app.utils.timing import utcnow

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": __version__,
        "env": settings.ENV,
        "time": utcnow().isoformat(),
    }


@router.get("/health/ready", summary="Readiness: database, models, workers")
async def ready(manager: ManagerDep) -> dict:
    """Unauthenticated on purpose -- a load balancer's probe cannot log in.

    That means per-camera detail (names, ids) does not belong here: this
    endpoint stays reachable by anyone, in any workspace, so it reports only
    aggregate counts. Anyone who needs the per-camera breakdown already has a
    bearer token and should use GET /monitoring/status instead.
    """
    database_ok = await check_database()
    strategies = registry.availability()
    workers = manager.worker_health()

    # A worker that is registered but not running means an exit is unmonitored,
    # which is the whole point of this service — surface it as degraded even
    # when the database is fine.
    workers_degraded = [w for w in workers if not w["alive"] or w["error"]]
    if database_ok and workers_degraded:
        status = "degraded"
    elif database_ok:
        status = "ok"
    else:
        status = "degraded"

    return {
        "status": status,
        "database": database_ok,
        "models_loaded": model_loader.loaded_models(),
        "strategies": strategies,
        "default_strategy": settings.DEFAULT_STRATEGY,
        "device": settings.DEVICE,
        "workers_total": len(workers),
        "workers_running": manager.running_count,
        "workers_degraded": len(workers_degraded),
        "pipeline": manager.pipeline_health(),
        "time": utcnow().isoformat(),
    }
