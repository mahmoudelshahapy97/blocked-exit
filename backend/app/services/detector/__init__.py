"""Pluggable blockage-detection strategies."""

from app.services.detector.base import (
    BlockageStrategy,
    CameraContext,
    classify,
)
from app.services.detector.door_centric import DoorCentricStrategy
from app.services.detector.registry import (
    available_strategies,
    build_strategy,
    get_shared_strategy,
    strategy_for_camera,
)
from app.services.detector.zone_based import ZoneBasedStrategy

__all__ = [
    "BlockageStrategy",
    "CameraContext",
    "DoorCentricStrategy",
    "ZoneBasedStrategy",
    "available_strategies",
    "build_strategy",
    "classify",
    "get_shared_strategy",
    "strategy_for_camera",
]
