"""Zone-based strategy, exercised with a stubbed detector.

No ultralytics weights are needed: `_infer` is replaced with a fake result, so
these tests cover the part we wrote — polygon rasterization, occupancy, object
attribution and state classification.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.core.enums import BlockageState
from app.services.detector.base import CameraContext
from app.services.detector.zone_based import ZoneBasedStrategy


class FakeTensor:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def cpu(self) -> FakeTensor:
        return self

    def numpy(self) -> np.ndarray:
        return self._array


class FakeBoxes:
    def __init__(self, xyxy, cls, conf, ids=None) -> None:
        self.xyxy = FakeTensor(np.asarray(xyxy, dtype=np.float32))
        self.cls = FakeTensor(np.asarray(cls, dtype=np.float32))
        self.conf = FakeTensor(np.asarray(conf, dtype=np.float32))
        self.id = FakeTensor(np.asarray(ids, dtype=np.float32)) if ids else None

    def __len__(self) -> int:
        return len(self.xyxy.numpy())


class FakeResult:
    def __init__(self, boxes: FakeBoxes | None) -> None:
        self.boxes = boxes
        self.masks = None


DOOR = [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]  # left half of the frame


@pytest.fixture
def frame() -> np.ndarray:
    return np.zeros((200, 200, 3), dtype=np.uint8)


@pytest.fixture
def camera() -> CameraContext:
    return CameraContext(id=1, name="Exit A", door_polygon=DOOR)


def build(result: FakeResult | None) -> ZoneBasedStrategy:
    strategy = ZoneBasedStrategy()
    strategy._names = {0: "person", 56: "chair"}
    strategy._infer = lambda frame, track=True: result  # type: ignore[assignment]
    return strategy


def test_empty_scene_is_fully_accessible(frame, camera):
    result = build(FakeResult(None)).analyze(frame, camera)
    assert result.accessibility_pct == 100.0
    assert result.raw_state is BlockageState.CLEAR
    assert result.blocking_objects == []


def test_object_outside_the_door_polygon_is_ignored(frame, camera):
    # Door is the left half; this chair sits entirely in the right half.
    boxes = FakeBoxes([[120, 0, 200, 200]], [56], [0.9])
    result = build(FakeResult(boxes)).analyze(frame, camera)
    assert result.accessibility_pct == 100.0
    assert result.blocking_objects == []


def test_half_blocked_door_reports_partial(frame, camera):
    # Covers the top half of the 100x200px door region.
    boxes = FakeBoxes([[0, 0, 100, 100]], [56], [0.9], ids=[7])
    result = build(FakeResult(boxes)).analyze(frame, camera)

    assert 45 <= result.accessibility_pct <= 55
    assert result.raw_state is BlockageState.PARTIAL
    assert result.blocking_objects[0].label == "chair"
    assert result.blocking_objects[0].track_id == 7


def test_fully_blocked_door(frame, camera):
    boxes = FakeBoxes([[0, 0, 100, 200]], [56], [0.95])
    result = build(FakeResult(boxes)).analyze(frame, camera)
    assert result.accessibility_pct < 5.0
    assert result.raw_state is BlockageState.FULL


def test_people_are_counted(frame, camera):
    boxes = FakeBoxes(
        [[0, 0, 40, 100], [40, 0, 80, 100]], [0, 0], [0.9, 0.8], ids=[1, 2]
    )
    result = build(FakeResult(boxes)).analyze(frame, camera)
    assert result.people_count == 2


def test_objects_are_ranked_by_how_much_they_block(frame, camera):
    boxes = FakeBoxes(
        [[0, 0, 20, 40], [0, 0, 100, 150]], [0, 56], [0.9, 0.9], ids=[1, 2]
    )
    result = build(FakeResult(boxes)).analyze(frame, camera)
    assert result.blocking_objects[0].label == "chair"
    assert result.blocking_objects[0].area_pct > result.blocking_objects[1].area_pct


def test_missing_polygon_falls_back_to_the_whole_frame_with_a_warning(frame):
    camera = CameraContext(id=2, name="Unconfigured", door_polygon=None)
    result = build(FakeResult(None)).analyze(frame, camera)
    assert result.warnings
    assert "door polygon" in result.warnings[0].lower()


def test_camera_thresholds_override_the_defaults(frame):
    strict = CameraContext(
        id=3, name="Strict", door_polygon=DOOR, clear_min_pct=99.0, full_max_pct=90.0
    )
    boxes = FakeBoxes([[0, 0, 100, 10]], [56], [0.9])  # ~5% of the door
    result = build(FakeResult(boxes)).analyze(frame, strict)
    # 95% accessible is CLEAR under the defaults, but this camera demands 99%.
    assert result.accessibility_pct > 90
    assert result.raw_state is BlockageState.PARTIAL

    lenient = CameraContext(
        id=4, name="Lenient", door_polygon=DOOR, clear_min_pct=90.0
    )
    assert (
        build(FakeResult(boxes)).analyze(frame, lenient).raw_state
        is BlockageState.CLEAR
    )
