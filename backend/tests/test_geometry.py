"""Occupancy math — the numbers behind the accessibility percentage."""

from __future__ import annotations

import numpy as np

from app.utils.geometry import (
    bbox_area,
    bbox_iou,
    bbox_to_mask,
    intersection_ratio,
    mask_area,
    occupancy,
    polygon_to_mask,
    resize_mask,
)

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def test_polygon_to_mask_covers_full_frame():
    mask = polygon_to_mask(SQUARE, 100, 100)
    assert mask.shape == (100, 100)
    assert mask_area(mask) == 100 * 100


def test_polygon_to_mask_covers_half_frame():
    half = [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]]
    mask = polygon_to_mask(half, 100, 100)
    assert abs(mask_area(mask) - 5000) <= 100  # rasterization slack


def test_occupancy_of_disjoint_obstacle_is_zero():
    door = polygon_to_mask([[0.0, 0.0], [0.4, 0.0], [0.4, 1.0], [0.0, 1.0]], 100, 100)
    far_away = bbox_to_mask([60, 0, 100, 100], 100, 100)
    assert occupancy(door, [far_away]) == 0.0


def test_occupancy_half_covered_door():
    door = polygon_to_mask(SQUARE, 100, 100)
    obstacle = bbox_to_mask([0, 0, 50, 100], 100, 100)
    assert abs(occupancy(door, [obstacle]) - 0.5) < 0.01


def test_overlapping_obstacles_are_not_double_counted():
    door = polygon_to_mask(SQUARE, 100, 100)
    left = bbox_to_mask([0, 0, 50, 100], 100, 100)
    overlapping = bbox_to_mask([25, 0, 60, 100], 100, 100)
    ratio = occupancy(door, [left, overlapping])
    # Union is 0..60 => 60%, not 50% + 35%.
    assert abs(ratio - 0.6) < 0.02


def test_accessibility_is_the_complement_of_occupancy():
    door = polygon_to_mask(SQUARE, 80, 80)
    obstacle = bbox_to_mask([0, 0, 20, 80], 80, 80)
    accessibility = 100.0 - occupancy(door, [obstacle]) * 100.0
    assert abs(accessibility - 75.0) < 1.0


def test_intersection_ratio_uses_region_as_denominator():
    door = bbox_to_mask([0, 0, 50, 50], 100, 100)
    huge = bbox_to_mask([0, 0, 100, 100], 100, 100)
    assert intersection_ratio(door, huge) == 1.0


def test_bbox_helpers():
    assert bbox_area([0, 0, 10, 10]) == 100
    assert bbox_area([10, 10, 0, 0]) == 0  # inverted box has no area
    assert bbox_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_resize_mask_preserves_binary_values():
    small = (np.ones((10, 10)) > 0).astype(np.uint8)
    resized = resize_mask(small, 40, 40)
    assert resized.shape == (40, 40)
    assert set(np.unique(resized)).issubset({0, 1})
