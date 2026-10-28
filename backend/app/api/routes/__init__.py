"""API route aggregation."""

from fastapi import APIRouter

from app.api.routes import (
    alerts,
    analytics,
    audit,
    auth,
    cameras,
    events,
    health,
    monitoring,
    notifications,
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
api_router.include_router(notifications.router)
api_router.include_router(audit.router)

__all__ = ["api_router"]
