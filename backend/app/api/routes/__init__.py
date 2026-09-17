"""API route aggregation."""

from fastapi import APIRouter

from app.api.routes import (
    alerts,
    analytics,
    auth,
    cameras,
    events,
    health,
    monitoring,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(cameras.router)
api_router.include_router(monitoring.router)
api_router.include_router(events.router)
api_router.include_router(alerts.router)
api_router.include_router(analytics.router)

__all__ = ["api_router"]
