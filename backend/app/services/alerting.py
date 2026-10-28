"""Alert delivery: webhook + email, with duration gating and cooldown.

Nothing is sent for a blockage that has not persisted past
``ALERT_MIN_DURATION_S``, and a camera cannot alert again within
``ALERT_COOLDOWN_S`` unless the situation escalates (PARTIAL -> FULL). That
policy lives in :class:`AlertPolicy` so the worker can consult it without
touching the database.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import session_scope
from app.core.enums import AlertChannel, AlertStatus, BlockageState
from app.core.logging import get_logger
from app.models.alert import Alert
from app.models.user import User, WorkspaceMember
from app.utils.timing import utcnow

logger = get_logger(__name__)


@dataclass
class AlertPolicy:
    """Per-camera gate deciding whether an alert may fire right now."""

    min_duration_s: float = field(default_factory=lambda: settings.ALERT_MIN_DURATION_S)
    cooldown_s: float = field(default_factory=lambda: settings.ALERT_COOLDOWN_S)

    _last_sent_at: float | None = field(default=None, init=False)
    _last_state: BlockageState = field(default=BlockageState.UNKNOWN, init=False)

    def should_alert(
        self, *, state: BlockageState, duration_s: float, now: float
    ) -> bool:
        if not settings.ALERTS_ENABLED or not state.is_blocked():
            return False
        if duration_s < self.min_duration_s:
            return False
        escalated = state.severity > self._last_state.severity
        if self._last_sent_at is not None and not escalated:
            if now - self._last_sent_at < self.cooldown_s:
                return False
        return True

    def mark_sent(self, *, state: BlockageState, now: float) -> None:
        self._last_sent_at = now
        self._last_state = state

    def reset(self) -> None:
        self._last_sent_at = None
        self._last_state = BlockageState.UNKNOWN


def build_payload(
    *,
    camera_id: int,
    camera_name: str,
    location: str | None,
    state: BlockageState,
    accessibility_pct: float,
    blocked_duration_s: float,
    risk_score: float,
    risk_level: str,
    recommended_action: str,
    blocking_objects: list[dict],
    strategy: str,
    event_id: int | None = None,
    occurred_at: datetime | None = None,
) -> dict:
    """The JSON body delivered to webhooks and embedded in emails."""
    return {
        "event": "exit_blocked",
        "event_id": event_id,
        "camera_id": camera_id,
        "camera_name": camera_name,
        "location": location,
        "state": state.value,
        "blocked": state.is_blocked(),
        "accessibility_pct": round(accessibility_pct, 2),
        "door_visible_pct": round(accessibility_pct, 2),
        "blocked_duration_s": round(blocked_duration_s, 1),
        "blocking_objects": blocking_objects,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommended_action": recommended_action,
        "strategy": strategy,
        "occurred_at": (occurred_at or utcnow()).isoformat(),
    }


async def dispatch(
    payload: dict,
    *,
    workspace_id: int,
    camera_id: int,
    event_id: int | None = None,
    snapshot: bytes | None = None,
    channels: list[AlertChannel] | None = None,
) -> list[Alert]:
    """Deliver on every configured channel and record the outcome.

    Delivery failures are recorded, never raised — a dead SMTP server must not
    stop the monitoring pipeline.
    """
    recipients = await _email_recipients(workspace_id) if settings.SMTP_HOST else []
    targets = channels or _configured_channels(bool(recipients))
    if not targets:
        logger.info("Alert for camera %s not sent: no channel configured", camera_id)
        return []

    results = await asyncio.gather(
        *(_deliver(channel, payload, snapshot, recipients) for channel in targets),
        return_exceptions=True,
    )

    rows: list[Alert] = []
    async with session_scope() as session:
        for channel, outcome in zip(targets, results, strict=True):
            error = None
            if isinstance(outcome, BaseException):
                status = AlertStatus.FAILED
                error = str(outcome)
                logger.warning("Alert via %s failed: %s", channel.value, error)
            else:
                status = outcome
            row = Alert(
                workspace_id=workspace_id,
                camera_id=camera_id,
                event_id=event_id,
                channel=channel.value,
                status=status.value,
                error=error,
                payload=payload,
                sent_at=utcnow() if status is AlertStatus.SENT else None,
            )
            session.add(row)
            rows.append(row)
    return rows


def _configured_channels(has_recipients: bool | None = None) -> list[AlertChannel]:
    channels: list[AlertChannel] = []
    if settings.WEBHOOK_URL:
        channels.append(AlertChannel.WEBHOOK)
    if has_recipients is None:
        has_recipients = bool(settings.ALERT_EMAIL_TO)
    if settings.SMTP_HOST and has_recipients:
        channels.append(AlertChannel.EMAIL)
    return channels


async def _email_recipients(workspace_id: int | None) -> list[str]:
    """ALERT_EMAIL_TO, plus every active account that can see the workspace
    (its members, every superadmin) and switched alert email on."""
    addresses = list(settings.ALERT_EMAIL_TO)
    if workspace_id is None:
        return addresses
    try:
        async with session_scope() as session:
            members = select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id
            )
            rows = await session.execute(
                select(User.email).where(
                    User.is_active.is_(True),
                    User.notify_email.is_(True),
                    or_(User.role == "superadmin", User.id.in_(members)),
                )
            )
            for (email,) in rows:
                if email and email not in addresses:
                    addresses.append(email)
    except Exception:
        logger.exception("Could not look up alert email recipients")
    return addresses


async def _deliver(
    channel: AlertChannel,
    payload: dict,
    snapshot: bytes | None,
    recipients: list[str] | None = None,
) -> AlertStatus:
    if channel is AlertChannel.WEBHOOK:
        return await _send_webhook(payload, snapshot)
    if channel is AlertChannel.EMAIL:
        return await _send_email(payload, snapshot, recipients)
    return AlertStatus.SKIPPED


_http_client = None
_http_lock = asyncio.Lock()


async def _get_http_client():
    """One shared client for the process.

    A client per alert means a fresh TCP handshake and TLS negotiation for every
    delivery, and a new connection pool discarded moments later. Alerts fire
    when things are going wrong — that is the worst moment to add latency.
    """
    global _http_client
    if _http_client is not None:
        return _http_client
    import httpx

    async with _http_lock:
        if _http_client is None:
            _http_client = httpx.AsyncClient(
                timeout=settings.WEBHOOK_TIMEOUT_S,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
    return _http_client


async def close_http_client() -> None:
    """Close the shared client during shutdown."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def _send_webhook(payload: dict, snapshot: bytes | None) -> AlertStatus:
    if not settings.WEBHOOK_URL:
        return AlertStatus.SKIPPED
    import httpx

    body = dict(payload)
    if snapshot:
        body["snapshot_jpeg_base64"] = base64.b64encode(snapshot).decode("ascii")

    client = await _get_http_client()
    attempts = max(0, settings.WEBHOOK_RETRIES) + 1
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = await client.post(settings.WEBHOOK_URL, json=body)
            response.raise_for_status()
            return AlertStatus.SENT
        except httpx.HTTPStatusError as exc:
            # 4xx means the request itself is wrong; repeating it verbatim will
            # fail identically. Only server-side and transport errors are retried.
            if exc.response.status_code < 500:
                raise
            last_error = exc
        except httpx.HTTPError as exc:
            last_error = exc

        if attempt < attempts:
            delay = 0.5 * (2 ** (attempt - 1))
            logger.warning(
                "Webhook attempt %d/%d failed (%s) — retrying in %.1fs",
                attempt,
                attempts,
                last_error,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error if last_error else RuntimeError("webhook delivery failed")


async def _send_email(
    payload: dict, snapshot: bytes | None, recipients: list[str] | None = None
) -> AlertStatus:
    recipients = list(settings.ALERT_EMAIL_TO) if recipients is None else recipients
    if not (settings.SMTP_HOST and recipients):
        return AlertStatus.SKIPPED
    import aiosmtplib

    # One message per address: a shared To: line would hand every recipient
    # the whole list.
    for address in recipients:
        message = EmailMessage()
        sender = settings.ALERT_EMAIL_FROM or settings.SMTP_USER or "insighteye"
        message["From"] = sender
        message["To"] = address
        message["Subject"] = (
            f"[{payload['state']}] Exit blocked — {payload['camera_name']} "
            f"({payload['accessibility_pct']}% accessible)"
        )
        message.set_content(_email_body(payload))
        if snapshot:
            message.add_attachment(
                snapshot, maintype="image", subtype="jpeg", filename="blocked_exit.jpg"
            )
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS,
        )
    return AlertStatus.SENT


def _email_body(payload: dict) -> str:
    objects = payload.get("blocking_objects") or []
    listed = (
        "\n".join(
            f"  - {obj.get('label')} ({obj.get('area_pct', 0)}% of the exit)"
            for obj in objects
        )
        or "  - (not identified — door-centric detection)"
    )
    return (
        f"Exit: {payload['camera_name']} ({payload.get('location') or 'no location'})\n"
        f"State: {payload['state']}\n"
        f"Accessible: {payload['accessibility_pct']}%\n"
        f"Blocked for: {payload['blocked_duration_s']}s\n"
        f"Risk: {payload['risk_score']}/100 ({payload['risk_level']})\n"
        f"Action: {payload['recommended_action']}\n"
        f"Detected by: {payload['strategy']} at {payload['occurred_at']}\n\n"
        f"Blocking objects:\n{listed}\n"
    )
