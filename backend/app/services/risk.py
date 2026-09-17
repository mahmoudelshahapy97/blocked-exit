"""Risk scoring: turn a verdict into an operational priority.

Four weighted factors (weights configurable in .env):

* how much of the exit is gone,
* how long it has been that way,
* how many people are in the area (an evacuation crowd raises the stakes),
* what is blocking it — a pallet is worse than a person who can walk away.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.enums import BlockageState, RiskLevel
from app.schemas.detection import BlockingObject
from app.utils.geometry import clamp

# How immovable each obstacle type is, 0..1.
CLASS_WEIGHTS: dict[str, float] = {
    "person": 0.35,
    "backpack": 0.45,
    "handbag": 0.45,
    "suitcase": 0.65,
    "chair": 0.70,
    "bench": 0.80,
    "potted plant": 0.60,
    "couch": 0.95,
    "bed": 0.95,
    "dining table": 0.90,
    "refrigerator": 1.0,
    "tv": 0.70,
    "laptop": 0.30,
    "bicycle": 0.75,
    "motorcycle": 0.90,
}
DEFAULT_CLASS_WEIGHT = 0.6

_ACTIONS = {
    RiskLevel.LOW: "No action required",
    RiskLevel.MEDIUM: "Inspect the exit and remove the obstruction",
    RiskLevel.HIGH: "Dispatch staff to clear the exit",
    RiskLevel.CRITICAL: "Clear Exit Immediately",
}


@dataclass
class RiskAssessment:
    score: float
    level: RiskLevel
    recommended_action: str


def _duration_factor(duration_s: float) -> float:
    saturation = max(1.0, settings.RISK_DURATION_SATURATION_S)
    return clamp(duration_s / saturation, 0.0, 1.0)


def _people_factor(people_count: int) -> float:
    # Saturates at 5 people in/around the exit region.
    return clamp(people_count / 5.0, 0.0, 1.0)


def _class_factor(objects: list[BlockingObject]) -> float:
    if not objects:
        return 0.0
    return max(
        CLASS_WEIGHTS.get(obj.label.lower(), DEFAULT_CLASS_WEIGHT) for obj in objects
    )


def _level(score: float, state: BlockageState) -> RiskLevel:
    if state is BlockageState.FULL and score >= 60:
        return RiskLevel.CRITICAL
    if score >= 80:
        return RiskLevel.CRITICAL
    if score >= 55:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MEDIUM
    # LOW is reserved for an accessible exit: an alert that says "blocked" must
    # never also say "no action required".
    return RiskLevel.MEDIUM if state.is_blocked() else RiskLevel.LOW


def assess(
    *,
    state: BlockageState,
    accessibility_pct: float,
    blocked_duration_s: float,
    blocking_objects: list[BlockingObject] | None = None,
    people_count: int = 0,
) -> RiskAssessment:
    """Score 0–100 and the action it implies."""
    if not state.is_blocked():
        return RiskAssessment(0.0, RiskLevel.LOW, _ACTIONS[RiskLevel.LOW])

    objects = blocking_objects or []
    score = (
        settings.RISK_W_ACCESSIBILITY * clamp(100.0 - accessibility_pct)
        + settings.RISK_W_DURATION * _duration_factor(blocked_duration_s) * 100.0
        + settings.RISK_W_PEOPLE * _people_factor(people_count) * 100.0
        + settings.RISK_W_CLASS * _class_factor(objects) * 100.0
    )
    score = round(clamp(score), 1)
    level = _level(score, state)
    return RiskAssessment(score, level, _ACTIONS[level])
