"""Strategy resolution.

Workers get a *dedicated* strategy instance (own model, own tracker state);
one-off callers share a lazily-built singleton. An unavailable strategy — most
often door-centric before door weights exist — falls back to the configured
default so the API keeps answering instead of erroring.
"""

from __future__ import annotations

import threading

from app.core.config import settings
from app.core.enums import StrategyName
from app.core.logging import get_logger
from app.services.detector.base import BlockageStrategy, CameraContext
from app.services.detector.door_centric import DoorCentricStrategy
from app.services.detector.zone_based import ZoneBasedStrategy

logger = get_logger(__name__)

_BUILDERS = {
    StrategyName.ZONE_BASED.value: ZoneBasedStrategy,
    StrategyName.DOOR_CENTRIC.value: DoorCentricStrategy,
}

_shared: dict[str, BlockageStrategy] = {}
_lock = threading.Lock()


def available_strategies() -> list[str]:
    return list(_BUILDERS)


def build_strategy(name: str, *, dedicated: bool = True) -> BlockageStrategy:
    """Instantiate a strategy, falling back to the default when unavailable."""
    resolved = name if name in _BUILDERS else settings.DEFAULT_STRATEGY
    if resolved != name:
        logger.warning("Unknown strategy %r — falling back to %r", name, resolved)

    strategy = _BUILDERS[resolved](dedicated=dedicated)
    if strategy.is_available():
        return strategy

    fallback = settings.DEFAULT_STRATEGY
    if fallback == resolved:
        # Default itself is unusable; return it anyway so the caller surfaces a
        # clear model-unavailable error rather than a confusing fallback loop.
        return strategy

    logger.warning(
        "Strategy %r is unavailable (missing weights?) — falling back to %r",
        resolved,
        fallback,
    )
    return _BUILDERS[fallback](dedicated=dedicated)


def get_shared_strategy(name: str) -> BlockageStrategy:
    """Process-wide instance, for calibration and single-frame analysis."""
    resolved = name if name in _BUILDERS else settings.DEFAULT_STRATEGY
    strategy = _shared.get(resolved)
    if strategy is not None:
        return strategy
    with _lock:
        strategy = _shared.get(resolved)
        if strategy is None:
            strategy = build_strategy(resolved, dedicated=False)
            _shared[strategy.name] = strategy
        return strategy


def strategy_for_camera(camera: CameraContext, *, dedicated: bool = True):
    return build_strategy(
        camera.strategy or settings.DEFAULT_STRATEGY, dedicated=dedicated
    )


def availability() -> dict[str, bool]:
    """Which strategies can actually run right now (used by /health/ready)."""
    status: dict[str, bool] = {}
    for name, builder in _BUILDERS.items():
        try:
            status[name] = builder(dedicated=False).is_available()
        except Exception:
            status[name] = False
    return status
