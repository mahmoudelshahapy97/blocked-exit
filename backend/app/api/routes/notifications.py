"""The caller's notifications: the bell's list, read marks, a test one, and
the socket that pushes new ones.

Addressed to an account, not the active workspace: the bell shows every
workspace the caller can see, and each row names its own.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from app.api.deps import CurrentUserDep, SessionDep
from app.core.config import settings
from app.core.database import SessionFactory
from app.core.enums import TokenType
from app.core.exceptions import NotFoundError
from app.core.security import TokenError, decode_token
from app.services import auth as auth_service
from app.services import inbox

router = APIRouter(prefix="/notifications", tags=["notifications"])

# 4401 is "authenticate again": a bad, expired or revoked token. The console
# then refreshes its token through any HTTP call and reconnects.
CLOSE_UNAUTHORIZED = 4401
AUTH_TIMEOUT_S = 10.0


class ReadRequest(BaseModel):
    notification_ids: list[int] | None = None


@router.get("")
async def list_notifications(
    session: SessionDep,
    user: CurrentUserDep,
    unread_only: bool = Query(False),
    kind: str | None = Query(None, max_length=32),
    workspace_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    before: datetime | None = Query(None),
) -> dict:
    """The caller's notifications, newest first: {items, total, unread}."""
    return await inbox.list_for(
        session,
        user.id,
        unread_only=unread_only,
        kind=kind,
        workspace_id=workspace_id,
        limit=limit,
        offset=offset,
        before=before,
    )


@router.get("/unread-count")
async def unread_count(session: SessionDep, user: CurrentUserDep) -> dict:
    return {"unread": await inbox.unread_count(session, user.id)}


@router.post("/read")
async def mark_read(
    payload: ReadRequest, session: SessionDep, user: CurrentUserDep
) -> dict:
    """The listed notifications, or all of them when none are listed."""
    changed = await inbox.mark_read(session, user.id, payload.notification_ids)
    return {"marked": len(changed), "unread": await inbox.unread_count(session, user.id)}


@router.delete("/{notification_id}/read")
async def mark_unread(
    notification_id: int, session: SessionDep, user: CurrentUserDep
) -> dict:
    if not await inbox.mark_unread(session, user.id, notification_id):
        raise NotFoundError("Notification not found")
    return {"unread": await inbox.unread_count(session, user.id)}


@router.post("/test", status_code=status.HTTP_201_CREATED)
async def send_test(user: CurrentUserDep) -> dict:
    """A notification to yourself, to check the bell and the socket end to end."""
    sent = await inbox.notify(
        [user.id],
        kind="system",
        severity="info",
        title="Test notification",
        message="Notifications reach this console.",
        link="/notifications",
    )
    return {"sent": sent}


async def _user_for(token: str | None):
    """The same checks as get_current_user, for a socket: valid access token,
    not revoked, account active, not issued before a password change."""
    if not token:
        return None, None
    try:
        claims = decode_token(token, expected_type=TokenType.ACCESS)
    except TokenError:
        return None, None
    async with SessionFactory() as session:
        jti = claims.get("jti")
        if jti and await auth_service.is_revoked(session, jti):
            return None, None
        user = await auth_service.get_user_by_id(session, int(claims["sub"]))
        if user is None or not user.is_active:
            return None, None
        if await auth_service.issued_before_cutoff(session, user.id, claims.get("iat")):
            return None, None
        return user, claims


@router.websocket("/ws")
async def notification_socket(websocket: WebSocket) -> None:
    """Pushes the caller's new notifications as they are raised.

    The access token comes in the first message, ``{"type": "auth", "token":
    ...}``: never in the URL (proxies log it). The server then sends
    ``hello {unread}``, then ``notification``, ``read``, ``resync`` and ``ping``
    messages, and closes with 4401 once the token expires or the session ends.
    """
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_S)
        token = (
            first.get("token")
            if isinstance(first, dict) and first.get("type") == "auth"
            else None
        )
        user, claims = await _user_for(token)
    except WebSocketDisconnect:
        return
    except (TimeoutError, ValueError):
        user = None
    if user is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Authenticate first.")
        return

    queue = inbox.hub.subscribe(user.id)
    receiver = asyncio.create_task(_drain(websocket))
    getter: asyncio.Task | None = None
    try:
        async with SessionFactory() as session:
            unread = await inbox.unread_count(session, user.id)
        await websocket.send_json({"type": "hello", "unread": unread})
        next_check = time.monotonic() + settings.NOTIFICATION_WS_PING_S
        while True:
            getter = getter or asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {getter, receiver},
                timeout=max(0.0, next_check - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if receiver in done:
                break
            if getter in done:
                await websocket.send_json(getter.result())
                getter = None
            if time.time() >= claims["exp"]:
                await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Token expired.")
                break
            if time.monotonic() >= next_check:
                # The same re-check every HTTP request gets.
                if (await _user_for(token))[0] is None:
                    await websocket.close(
                        code=CLOSE_UNAUTHORIZED, reason="Session ended."
                    )
                    break
                await websocket.send_json({"type": "ping"})
                next_check = time.monotonic() + settings.NOTIFICATION_WS_PING_S
    except (WebSocketDisconnect, RuntimeError):
        pass  # the browser went away mid-send
    finally:
        inbox.hub.unsubscribe(user.id, queue)
        for task in (getter, receiver):
            if task is not None:
                task.cancel()


async def _drain(websocket: WebSocket) -> None:
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        return
