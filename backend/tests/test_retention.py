"""Snapshot retention — the half that touches the disk.

The database half is exercised against a real Postgres in the integration
checks; these cover the file-eviction rules, which are where the arithmetic is.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.retention import purge_snapshots


@pytest.fixture
def snapshot_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "snapshots"
    (root / "camera_1").mkdir(parents=True)
    monkeypatch.setattr(settings, "SNAPSHOT_DIR", root)
    monkeypatch.setattr(settings, "SNAPSHOT_RETENTION_DAYS", 30)
    monkeypatch.setattr(settings, "SNAPSHOT_MAX_TOTAL_MB", 0)  # ceiling off
    return root


def write(root: Path, name: str, *, days_old: float = 0.0, size: int = 1024) -> Path:
    path = root / "camera_1" / name
    path.write_bytes(b"x" * size)
    if days_old:
        stamp = time.time() - days_old * 86400
        os.utime(path, (stamp, stamp))
    return path


def test_files_past_the_age_limit_are_deleted(snapshot_dir: Path):
    old = write(snapshot_dir, "old.jpg", days_old=45)
    recent = write(snapshot_dir, "recent.jpg", days_old=5)

    deleted, reclaimed = purge_snapshots()

    assert deleted == 1
    assert reclaimed == 1024
    assert not old.exists()
    assert recent.exists()


def test_a_file_exactly_at_the_boundary_is_kept(snapshot_dir: Path):
    """Retention is 'older than N days', not 'N days or older'."""
    edge = write(snapshot_dir, "edge.jpg", days_old=29.9)
    assert purge_snapshots() == (0, 0)
    assert edge.exists()


def test_age_limit_of_zero_disables_expiry(snapshot_dir: Path, monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_RETENTION_DAYS", 0)
    ancient = write(snapshot_dir, "ancient.jpg", days_old=3650)
    assert purge_snapshots() == (0, 0)
    assert ancient.exists()


def test_the_size_ceiling_evicts_oldest_first(snapshot_dir: Path, monkeypatch):
    """Age alone does not bound the disk — a busy week fills it well inside
    the retention window."""
    monkeypatch.setattr(settings, "SNAPSHOT_RETENTION_DAYS", 0)
    monkeypatch.setattr(settings, "SNAPSHOT_MAX_TOTAL_MB", 1)

    mb = 1024 * 1024
    oldest = write(snapshot_dir, "a.jpg", days_old=3, size=mb // 2)
    middle = write(snapshot_dir, "b.jpg", days_old=2, size=mb // 2)
    newest = write(snapshot_dir, "c.jpg", days_old=1, size=mb // 2)

    deleted, _ = purge_snapshots()

    assert deleted == 1
    assert not oldest.exists()
    assert middle.exists() and newest.exists()


def test_both_rules_apply_in_one_pass(snapshot_dir: Path, monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_MAX_TOTAL_MB", 1)
    mb = 1024 * 1024
    expired = write(snapshot_dir, "expired.jpg", days_old=60, size=1024)
    bulky_old = write(snapshot_dir, "bulky_old.jpg", days_old=3, size=mb)
    bulky_new = write(snapshot_dir, "bulky_new.jpg", days_old=1, size=mb)

    deleted, _ = purge_snapshots()

    assert deleted == 2
    assert not expired.exists()
    assert not bulky_old.exists()
    assert bulky_new.exists()


def test_a_missing_snapshot_directory_is_not_an_error(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "SNAPSHOT_DIR", tmp_path / "does-not-exist")
    assert purge_snapshots() == (0, 0)


def test_non_jpeg_files_are_left_alone(snapshot_dir: Path):
    """Retention owns snapshots, not whatever else shares the volume."""
    note = snapshot_dir / "camera_1" / "README.txt"
    note.write_text("keep me")
    write(snapshot_dir, "old.jpg", days_old=45)

    purge_snapshots()

    assert note.exists()
