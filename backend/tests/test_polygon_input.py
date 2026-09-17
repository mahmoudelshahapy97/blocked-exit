"""Polygon input: what a drawing UI sends, and what gets stored.

Stored polygons are always normalized [0,1] — that is what makes a region
survive a camera being replaced with one of a different resolution.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.camera import CameraCreate, DoorPolygonUpdate
from app.utils.geometry import denormalize_polygon, normalize_polygon

# A doorway drawn on a 1920x1080 frame.
PIXEL_POLYGON = [[576, 162], [1344, 162], [1344, 1026], [576, 1026]]
FRAME_W, FRAME_H = 1920, 1080


def test_pixels_are_normalized_when_the_frame_size_is_given():
    payload = DoorPolygonUpdate(
        door_polygon=PIXEL_POLYGON, frame_width=FRAME_W, frame_height=FRAME_H
    )
    assert payload.door_polygon == [
        [0.3, 0.15],
        [0.7, 0.15],
        [0.7, 0.95],
        [0.3, 0.95],
    ]


def test_already_normalized_input_is_accepted_unchanged():
    normalized = [[0.3, 0.15], [0.7, 0.15], [0.7, 0.95], [0.3, 0.95]]
    assert DoorPolygonUpdate(door_polygon=normalized).door_polygon == normalized


def test_pixels_without_a_frame_size_are_rejected_with_a_usable_message():
    with pytest.raises(PydanticValidationError) as exc:
        DoorPolygonUpdate(door_polygon=PIXEL_POLYGON)
    message = str(exc.value)
    assert "frame_width" in message and "frame_height" in message


def test_frame_dimensions_must_come_as_a_pair():
    with pytest.raises(PydanticValidationError, match="together"):
        DoorPolygonUpdate(door_polygon=PIXEL_POLYGON, frame_width=FRAME_W)


def test_round_trip_through_pixels_and_back_is_stable():
    """What the editor draws is what the detector measures."""
    payload = DoorPolygonUpdate(
        door_polygon=PIXEL_POLYGON, frame_width=FRAME_W, frame_height=FRAME_H
    )
    back = denormalize_polygon(payload.door_polygon, FRAME_W, FRAME_H)
    assert back.tolist() == PIXEL_POLYGON


def test_a_region_drawn_on_one_resolution_maps_onto_another():
    """The reason coordinates are stored normalized at all."""
    normalized = normalize_polygon(PIXEL_POLYGON, FRAME_W, FRAME_H)
    on_720p = denormalize_polygon(normalized, 1280, 720)
    assert on_720p.tolist() == [[384, 108], [896, 108], [896, 684], [384, 684]]


def test_points_outside_the_frame_are_clamped_not_rejected():
    """A click a pixel past the edge is aim, not an error worth failing on."""
    payload = DoorPolygonUpdate(
        door_polygon=[[-5, -5], [1925, 0], [1920, 1085], [0, 1080]],
        frame_width=FRAME_W,
        frame_height=FRAME_H,
    )
    for x, y in payload.door_polygon:
        assert 0.0 <= x <= 1.0
        assert 0.0 <= y <= 1.0


def test_fewer_than_three_points_is_not_a_region():
    with pytest.raises(PydanticValidationError, match="at least 3 points"):
        DoorPolygonUpdate(door_polygon=[[0.1, 0.1], [0.9, 0.9]])


def test_malformed_points_are_reported_before_any_conversion_maths():
    with pytest.raises(PydanticValidationError, match=r"\[x, y\]"):
        DoorPolygonUpdate(
            door_polygon=[[0, 0, 0], [10, 0], [10, 10]],
            frame_width=FRAME_W,
            frame_height=FRAME_H,
        )


def test_camera_create_still_requires_normalized_coordinates():
    """Only the door-polygon endpoint takes pixels; create keeps its contract."""
    with pytest.raises(PydanticValidationError, match="pixels"):
        CameraCreate(name="Exit A", rtsp_url="clip.mp4", door_polygon=PIXEL_POLYGON)


def test_zero_frame_size_is_refused():
    with pytest.raises(PydanticValidationError):
        DoorPolygonUpdate(
            door_polygon=PIXEL_POLYGON, frame_width=0, frame_height=FRAME_H
        )
