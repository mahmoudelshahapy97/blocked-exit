"""Bounded storage: expire old events, alerts and snapshots.

A monitoring service that only ever inserts will eventually fill its disk and
take the monitoring down with it — the failure this whole system exists to
prevent, caused by the system itself. Every retention limit here is a setting,
and the whole job can be turned off (`RETENTION_ENABLED=false`) for deployments
where an external archiver owns the data instead.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import session_scope
from app.core.logging import get_logger
from app.models.alert import Alert
from app.models.event import BlockageEvent
from app.utils.timing import utcnow

logger = get_logger(__name__)

_task: asyncio.Task | None = None


@dataclass
class PurgeReport:
    """What a single retention pass removed."""

    events_deleted: int = 0
    alerts_deleted: int = 0
    snapshots_deleted: int = 0
    bytes_reclaimed: int = 0

    @property
    def empty(self) -> bool:
        return not (self.events_deleted or self.alerts_deleted or self.snapshots_deleted)

    def as_dict(self) -> dict:
        return {
            "events_deleted": self.events_deleted,
            "alerts_deleted": self.alerts_deleted,
            "snapshots_deleted": self.snapshots_deleted,
            "mb_reclaimed": round(self.bytes_reclaimed / (1024 * 1024), 1),
        }


async def purge_old_data() -> PurgeReport:
    """Run one full retention pass. Never raises — a purge failure is not fatal."""
    report = PurgeReport()
    try:
        report.alerts_deleted = await _purge_alerts()
        report.events_deleted = await _purge_events()
    except Exception:
        logger.exception("Database retention pass failed")

    try:
        deleted, reclaimed = await asyncio.to_thread(purge_snapshots)
        report.snapshots_deleted = deleted
        report.bytes_reclaimed = reclaimed
    except Exception:
        logger.exception("Snapshot retention pass failed")

    return report


async def _purge_alerts() -> int:
    if settings.ALERT_RETENTION_DAYS <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.ALERT_RETENTION_DAYS)
    async with session_scope() as session:
        result = await session.execute(delete(Alert).where(Alert.created_at < cutoff))
    return result.rowcount or 0


async def _purge_events() -> int:
    """Delete expired events; their alerts cascade.

    Open events are never deleted regardless of age — one still marked ongoing
    is either a real blockage or a reconciliation bug, and deleting it would
    hide both.
    """
    if settings.EVENT_RETENTION_DAYS <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.EVENT_RETENTION_DAYS)
    async with session_scope() as session:
        # Collect the snapshot paths first: the rows that name them are about
        # to disappear, and an unnamed file on disk is never reclaimed.
        paths = (
            (
                await session.execute(
                    select(BlockageEvent.snapshot_path).where(
                        BlockageEvent.started_at < cutoff,
                        BlockageEvent.ended_at.is_not(None),
                        BlockageEvent.snapshot_path.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        result = await session.execute(
            delete(BlockageEvent).where(
                BlockageEvent.started_at < cutoff,
                BlockageEvent.ended_at.is_not(None),
            )
        )

    for path in paths:
        _unlink(Path(path))
    return result.rowcount or 0


def purge_snapshots() -> tuple[int, int]:
    """Age out snapshot files, then enforce the total-size ceiling.

    Returns ``(files_deleted, bytes_reclaimed)``. Runs in a worker thread — this
    is filesystem work and stats every file under SNAPSHOT_DIR.
    """
    root = Path(settings.SNAPSHOT_DIR)
    if not root.is_dir():
        return 0, 0

    files: list[tuple[float, int, Path]] = []
    for path in root.rglob("*.jpg"):
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((stat.st_mtime, stat.st_size, path))

    deleted = 0
    reclaimed = 0

    if settings.SNAPSHOT_RETENTION_DAYS > 0:
        cutoff = utcnow().timestamp() - settings.SNAPSHOT_RETENTION_DAYS * 86400
        remaining: list[tuple[float, int, Path]] = []
        for mtime, size, path in files:
            if mtime < cutoff and _unlink(path):
                deleted += 1
                reclaimed += size
            else:
                remaining.append((mtime, size, path))
        files = remaining

    # Age alone does not bound the disk: a busy week can fill it well inside the
    # retention window, so a hard ceiling evicts oldest-first until it fits.
    if settings.SNAPSHOT_MAX_TOTAL_MB > 0:
        budget = settings.SNAPSHOT_MAX_TOTAL_MB * 1024 * 1024
        total = sum(size for _, size, _ in files)
        if total > budget:
            for _mtime, size, path in sorted(files):
                if total <= budget:
                    break
                if _unlink(path):
                    deleted += 1
                    reclaimed += size
                    total -= size

    return deleted, reclaimed


def _unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        logger.warning("Could not delete %s: %s", path, exc)
        return False


# -- background task ------------------------------------------------------
async def _loop() -> None:
    interval = max(60.0, settings.RETENTION_INTERVAL_S)
    while True:
        try:
            await asyncio.sleep(interval)
            report = await purge_old_data()
            if not report.empty:
                logger.info("Retention pass: %s", report.as_dict())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention loop iteration failed")


async def startup() -> None:
    global _task
    if not settings.RETENTION_ENABLED:
        logger.info("Retention is disabled (RETENTION_ENABLED=false)")
        return
    _task = asyncio.create_task(_loop(), name="retention")
    logger.info(
        "Retention active: events %dd, alerts %dd, snapshots %dd / %dMB",
        settings.EVENT_RETENTION_DAYS,
        settings.ALERT_RETENTION_DAYS,
        settings.SNAPSHOT_RETENTION_DAYS,
        settings.SNAPSHOT_MAX_TOTAL_MB,
    )


async def shutdown() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
