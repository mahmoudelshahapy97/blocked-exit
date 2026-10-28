"""The audit log: who did what, when and from where.

Two ways in:

- ``AuditMiddleware`` records every successful state-changing request whose
  route is listed in ``AUDITED_ROUTES`` (accounts, workspaces and members,
  cameras and their zones, workers, event triage, password changes). The
  acting account is the one ``get_current_user`` resolved for the request;
  the target is the route's path id.
- ``record()`` directly, for what the middleware cannot see: sign-ins (and
  failed ones), where nobody is authenticated yet.

Recording never fails the request: an insert that errors is logged.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any

from sqlalchemy import delete, func, select
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.database import session_scope
from app.models.audit import AuditLog
from app.models.user import Workspace

logger = logging.getLogger(__name__)

# (method, route path template under the API prefix, action, target type).
AUDITED_ROUTES: list[tuple[str, str, str, str]] = [
    ("POST", "/auth/logout", "auth.logout", "user"),
    ("PATCH", "/auth/me", "user.updated", "user"),
    ("POST", "/auth/me/password", "auth.password_changed", "user"),
    ("POST", "/auth/users", "user.created", "user"),
    ("PATCH", "/auth/users/{user_id}", "user.updated", "user"),
    ("POST", "/workspaces", "workspace.created", "workspace"),
    ("PATCH", "/workspaces/{workspace_id}", "workspace.updated", "workspace"),
    ("POST", "/workspaces/{workspace_id}/deactivate", "workspace.updated", "workspace"),
    ("DELETE", "/workspaces/{workspace_id}", "workspace.deleted", "workspace"),
    ("POST", "/workspaces/{workspace_id}/members", "workspace.member_added", "workspace"),
    (
        "PATCH",
        "/workspaces/{workspace_id}/members/{member_id}",
        "workspace.member_updated",
        "workspace",
    ),
    (
        "DELETE",
        "/workspaces/{workspace_id}/members/{member_id}",
        "workspace.member_removed",
        "workspace",
    ),
    ("POST", "/cameras", "camera.created", "camera"),
    ("PATCH", "/cameras/{camera_id}", "camera.updated", "camera"),
    ("DELETE", "/cameras/{camera_id}", "camera.deleted", "camera"),
    ("PUT", "/cameras/{camera_id}/door-polygon", "camera.updated", "camera"),
    ("POST", "/cameras/{camera_id}/reference", "camera.updated", "camera"),
    ("POST", "/monitoring/{camera_id}/start", "camera.started", "camera"),
    ("POST", "/monitoring/{camera_id}/stop", "camera.stopped", "camera"),
    ("POST", "/monitoring/{camera_id}/restart", "camera.started", "camera"),
    ("POST", "/events/{event_id}/acknowledge", "event.status_changed", "event"),
    ("POST", "/events/{event_id}/resolve", "event.status_changed", "event"),
    ("DELETE", "/events", "event.deleted", "event"),
    ("DELETE", "/events/all", "event.deleted", "event"),
]

_ACTIONS = {(m, p): (a, t) for m, p, a, t in AUDITED_ROUTES}
EXPORT_LIMIT = 50_000


def client_ip(scope_or_request: Any) -> str | None:
    """The caller's address: the first X-Forwarded-For hop when nginx set one."""
    headers = (
        dict(scope_or_request.get("headers") or [])
        if isinstance(scope_or_request, dict)
        else None
    )
    if headers is not None:
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        client = scope_or_request.get("client")
        host = client[0] if client else None
    else:
        forwarded = scope_or_request.headers.get("x-forwarded-for", "")
        host = scope_or_request.client.host if scope_or_request.client else None
    return forwarded.split(",")[0].strip() or host


async def record(
    action: str,
    *,
    user: Any = None,
    actor: str | None = None,
    status: str = "success",
    workspace_id: int | None = None,
    target_type: str | None = None,
    target_id: Any = None,
    target_label: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    data: dict | None = None,
) -> None:
    try:
        async with session_scope() as session:
            session.add(
                AuditLog(
                    user_id=user.id if user is not None else None,
                    actor=(actor or (user.username if user is not None else None) or "")[
                        :120
                    ]
                    or None,
                    workspace_id=workspace_id,
                    action=action,
                    status=status,
                    target_type=target_type,
                    target_id=str(target_id) if target_id is not None else None,
                    target_label=target_label,
                    ip=ip,
                    user_agent=(user_agent or "")[:300] or None,
                    request_id=request_id,
                    data=data or {},
                )
            )
    except Exception:
        logger.exception("Could not record audit entry %s", action)


def _conditions(filters: dict) -> list:
    conditions = []
    if filters.get("action"):
        conditions.append(AuditLog.action == filters["action"])
    if filters.get("actor"):
        conditions.append(AuditLog.actor.ilike(f"%{filters['actor']}%"))
    if filters.get("since"):
        conditions.append(AuditLog.created_at >= filters["since"])
    if filters.get("until"):
        conditions.append(AuditLog.created_at <= filters["until"])
    return conditions


async def list_entries(session, filters: dict, limit: int = 50, offset: int = 0) -> dict:
    conditions = _conditions(filters)
    total = (
        await session.scalar(
            select(func.count()).select_from(AuditLog).where(*conditions)
        )
        or 0
    )
    rows = await session.execute(
        select(AuditLog, Workspace.name)
        .outerjoin(Workspace, Workspace.id == AuditLog.workspace_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        {
            "audit_id": a.id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "user_id": a.user_id,
            "actor": a.actor,
            "workspace_id": a.workspace_id,
            "workspace_name": name,
            "action": a.action,
            "status": a.status,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "target_label": a.target_label,
            "ip": a.ip,
            "user_agent": a.user_agent,
            "request_id": a.request_id,
            "data": a.data or {},
        }
        for a, name in rows
    ]
    return {"items": items, "total": total}


async def export_csv(session, filters: dict) -> str:
    page = await list_entries(session, filters, limit=EXPORT_LIMIT)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "time",
            "actor",
            "action",
            "status",
            "target_type",
            "target_id",
            "target",
            "workspace",
            "ip",
            "user_agent",
        ]
    )
    for r in page["items"]:
        writer.writerow(
            [
                r["created_at"],
                r["actor"],
                r["action"],
                r["status"],
                r["target_type"],
                r["target_id"],
                r["target_label"],
                r["workspace_name"],
                r["ip"],
                r["user_agent"],
            ]
        )
    return csv_safe(out.getvalue())


async def purge_older_than(session, days: int) -> int:
    result = await session.execute(
        delete(AuditLog).where(
            AuditLog.created_at < func.now() - func.make_interval(0, 0, 0, days)
        )
    )
    return result.rowcount or 0


_FORMULA = re.compile(r'(^|,)(")?([=+\-@])', re.M)


def csv_safe(text: str) -> str:
    """Neutralise spreadsheet formulas (a camera named "=HYPERLINK(...)") by
    prefixing an apostrophe, and add a BOM so Excel reads UTF-8 (Arabic names)."""
    return "﻿" + _FORMULA.sub(
        lambda m: f"{m.group(1)}{m.group(2) or ''}'{m.group(3)}", text
    )


class AuditMiddleware:
    """Records audited routes after they succeed (2xx). Pure ASGI rather than
    @app.middleware("http") so streaming responses (MJPEG, clips) pass through
    untouched and only the status code is looked at."""

    def __init__(self, app: ASGIApp, api_prefix: str) -> None:
        self.app = app
        self.prefix = api_prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def capture(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, capture)

        if not 200 <= status_code < 300:
            return
        route = scope.get("route")
        template = getattr(route, "path", "") or ""
        if template.startswith(self.prefix):
            template = template[len(self.prefix) :]
        entry = _ACTIONS.get((scope["method"], template))
        if not entry:
            return
        action, target_type = entry
        state = scope.get("state") or {}
        user = state.get("audit_user")
        path_params = scope.get("path_params") or {}
        target_id = next(iter(path_params.values()), None)
        if target_id is None and user is not None and target_type == "user":
            target_id = user.id
        headers = dict(scope.get("headers") or [])
        # The active workspace is the user's own (POST /workspaces/{id}/activate).
        workspace_id = (
            getattr(user, "default_workspace_id", None) if user is not None else None
        )
        if target_type == "workspace" and target_id is not None:
            workspace_id = int(target_id)
        await record(
            action,
            user=user,
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=target_id,
            ip=client_ip(scope),
            user_agent=headers.get(b"user-agent", b"").decode() or None,
            request_id=state.get("request_id"),
        )
