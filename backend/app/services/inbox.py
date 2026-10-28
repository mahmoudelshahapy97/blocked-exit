"""In-app notifications: the console's bell, its Notifications page, and the
socket that pushes new ones as they are raised.

One ``notification`` row per account, so read marks are per person. A
workspace's notification goes to its active members plus every active
superadmin. Delivery to open consoles is an in-process hub (one asyncio queue
per open socket), which is enough because the API runs as a single replica:
the stream workers live in this process.

Nothing here raises into the caller: a failed insert is logged and the
monitoring pipeline carries on.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.database import session_scope
from app.models.camera import Camera
from app.models.notification import Notification
from app.models.user import User, Workspace, WorkspaceMember

logger = logging.getLogger(__name__)

SEVERITIES = ("info", "low", "medium", "high", "critical")
_QUEUE_SIZE = 100


def serialize(
    row: Notification, workspace_name: str | None = None, camera_name: str | None = None
) -> dict:
    return {
        "notification_id": row.id,
        "workspace_id": row.workspace_id,
        "workspace_name": workspace_name,
        "kind": row.kind,
        "severity": row.severity,
        "title": row.title,
        "message": row.message,
        "link": row.link,
        "camera_id": row.camera_id,
        "camera_name": camera_name or row.camera_name,
        "ref_id": row.ref_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
    }


class NotificationHub:
    """user id -> the queues of that account's open sockets."""

    def __init__(self) -> None:
        self._queues: dict[int, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._queues[user_id].add(queue)
        return queue

    def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        queues = self._queues.get(user_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                self._queues.pop(user_id, None)

    def publish(self, user_id: int, message: dict) -> None:
        for queue in list(self._queues.get(user_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A socket that stopped reading: drop its backlog and tell it
                # to refetch, rather than letting one slow tab hold memory.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "resync"})

    @property
    def socket_count(self) -> int:
        return sum(len(q) for q in self._queues.values())


hub = NotificationHub()


def _visible(user_id: int):
    """Rows from workspaces the account can still see: removing someone from
    a workspace (or deactivating it) also takes its alerts out of their bell.
    Rows with no workspace (tests) are always theirs."""
    superadmin = exists().where(and_(User.id == user_id, User.role == "superadmin"))
    member = exists().where(
        and_(
            WorkspaceMember.workspace_id == Notification.workspace_id,
            WorkspaceMember.user_id == user_id,
            Workspace.id == Notification.workspace_id,
            Workspace.is_active.is_(True),
        )
    )
    return and_(
        Notification.user_id == user_id,
        or_(Notification.workspace_id.is_(None), superadmin, member),
    )


async def workspace_recipients(session, workspace_id: int | None) -> list[int]:
    """Active members of the workspace, plus every active superadmin."""
    members = select(WorkspaceMember.user_id).where(
        WorkspaceMember.workspace_id == workspace_id
    )
    rows = await session.execute(
        select(User.id).where(
            User.is_active.is_(True),
            or_(User.role == "superadmin", User.id.in_(members)),
        )
    )
    return [r[0] for r in rows]


async def notify(
    user_ids,
    *,
    kind: str,
    title: str,
    message: str = "",
    severity: str = "info",
    workspace_id: int | None = None,
    link: str | None = None,
    camera_id: int | None = None,
    camera_name: str | None = None,
    ref_id: Any = None,
) -> int:
    """Store one notification per account and push it to their open
    consoles. With ``ref_id`` an account hears about a thing once only.
    Returns how many were stored."""
    user_ids = list(dict.fromkeys(user_ids))
    if not user_ids:
        return 0
    if severity not in SEVERITIES:
        severity = "info"
    values = [
        {
            "user_id": user_id,
            "workspace_id": workspace_id,
            "kind": kind,
            "severity": severity,
            "title": title[:200],
            "message": message,
            "link": link,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "ref_id": str(ref_id) if ref_id is not None else None,
        }
        for user_id in user_ids
    ]
    try:
        async with session_scope() as session:
            statement = insert(Notification).values(values)
            if ref_id is not None:
                statement = statement.on_conflict_do_nothing(
                    index_elements=["user_id", "kind", "ref_id"],
                    index_where=Notification.ref_id.is_not(None),
                )
            rows = (
                (await session.execute(statement.returning(Notification))).scalars().all()
            )
            workspace_name = None
            if workspace_id is not None:
                workspace_name = await session.scalar(
                    select(Workspace.name).where(Workspace.id == workspace_id)
                )
    except Exception:
        logger.exception("Could not store %s notification", kind)
        return 0
    for row in rows:
        hub.publish(
            row.user_id,
            {"type": "notification", "notification": serialize(row, workspace_name)},
        )
    return len(rows)


async def notify_workspace(workspace_id: int | None, **kwargs: Any) -> int:
    """notify() everyone who can see the workspace."""
    try:
        async with session_scope() as session:
            recipients = await workspace_recipients(session, workspace_id)
    except Exception:
        logger.exception("Could not look up notification recipients")
        return 0
    return await notify(recipients, workspace_id=workspace_id, **kwargs)


async def unread_count(session, user_id: int) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(_visible(user_id), Notification.read_at.is_(None))
        )
        or 0
    )


async def list_for(
    session,
    user_id: int,
    *,
    unread_only: bool = False,
    kind: str | None = None,
    workspace_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    before: datetime | None = None,
) -> dict:
    conditions = [_visible(user_id)]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    if kind:
        conditions.append(Notification.kind == kind)
    if workspace_id:
        conditions.append(Notification.workspace_id == workspace_id)
    if before:
        conditions.append(Notification.created_at < before)
    total = (
        await session.scalar(
            select(func.count()).select_from(Notification).where(*conditions)
        )
        or 0
    )
    rows = await session.execute(
        select(Notification, Workspace.name, Camera.name)
        .outerjoin(Workspace, Workspace.id == Notification.workspace_id)
        .outerjoin(Camera, Camera.id == Notification.camera_id)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        serialize(n, workspace_name, camera_name)
        for n, workspace_name, camera_name in rows
    ]
    return {
        "items": items,
        "total": total,
        "unread": await unread_count(session, user_id),
    }


async def mark_read(session, user_id: int, ids: list[int] | None = None) -> list[int]:
    """Mark the listed notifications read, or every unread one. Ids that are
    not the caller's, or already read, are ignored. Tells the account's other
    consoles."""
    statement = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if ids:
        statement = statement.where(Notification.id.in_(ids))
    changed = (
        (
            await session.execute(
                statement.values(read_at=func.now()).returning(Notification.id)
            )
        )
        .scalars()
        .all()
    )
    await session.commit()
    if changed:
        hub.publish(
            user_id,
            {
                "type": "read",
                "notification_ids": changed,
                "all": not ids,
                "unread": await unread_count(session, user_id),
            },
        )
    return list(changed)


async def mark_unread(session, user_id: int, notification_id: int) -> bool:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.id == notification_id)
        .values(read_at=None)
    )
    await session.commit()
    if result.rowcount:
        hub.publish(user_id, {"type": "resync"})
    return bool(result.rowcount)


async def purge_older_than(session, days: int) -> int:
    result = await session.execute(
        delete(Notification).where(
            Notification.created_at < func.now() - func.make_interval(0, 0, 0, days)
        )
    )
    return result.rowcount or 0
