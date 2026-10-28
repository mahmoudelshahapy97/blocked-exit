"""Per-episode detection confidence and the worst-risk rule."""

from __future__ import annotations

from app.schemas.detection import BlockingObject
from app.services.confidence import ConfidenceTracker
from app.services.stream_manager import _worse_risk


def _objs(*confidences: float) -> list[BlockingObject]:
    return [BlockingObject(label="chair", confidence=c) for c in confidences]


def test_samples_the_top_detection_of_each_frame():
    tracker = ConfidenceTracker()
    tracker.sample(_objs(0.4, 0.9))
    tracker.sample(_objs(0.5))
    assert tracker.values == {"confidence": 0.9, "avg_confidence": 0.7}


def test_frames_with_nothing_blocking_do_not_count():
    tracker = ConfidenceTracker()
    assert tracker.values == {"confidence": None, "avg_confidence": None}
    tracker.sample([])
    tracker.sample(_objs(0.6))
    tracker.sample([])
    assert tracker.values == {"confidence": 0.6, "avg_confidence": 0.6}


def test_reset_starts_a_new_episode():
    tracker = ConfidenceTracker()
    tracker.sample(_objs(0.95))
    tracker.reset()
    tracker.sample(_objs(0.3))
    assert tracker.values == {"confidence": 0.3, "avg_confidence": 0.3}


def test_an_event_keeps_its_worst_risk_band():
    assert _worse_risk(None, "MEDIUM") == "MEDIUM"
    assert _worse_risk("HIGH", "MEDIUM") == "HIGH"
    assert _worse_risk("HIGH", "CRITICAL") == "CRITICAL"
    assert _worse_risk("LOW", None) == "LOW"
