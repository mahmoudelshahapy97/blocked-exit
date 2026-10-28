"""Detection confidence of one blockage episode, for the confidence audit.

Per analysed frame the most confident blocking detection is sampled; the
episode reports the peak and the mean of those samples -- the platform's
`_StreamState.sample_confidence`. A frame with nothing blocking contributes
nothing, so a momentarily empty doorway does not drag the mean towards zero.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.detection import BlockingObject


class ConfidenceTracker:
    __slots__ = ("peak", "_sum", "_count")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.peak = 0.0
        self._sum = 0.0
        self._count = 0

    def sample(self, objects: Iterable[BlockingObject]) -> None:
        top = max((obj.confidence for obj in objects), default=None)
        if top is None:
            return
        self.peak = max(self.peak, float(top))
        self._sum += float(top)
        self._count += 1

    @property
    def values(self) -> dict[str, float | None]:
        """{"confidence": peak, "avg_confidence": mean}, None before any sample."""
        if not self._count:
            return {"confidence": None, "avg_confidence": None}
        return {
            "confidence": round(self.peak, 4),
            "avg_confidence": round(self._sum / self._count, 4),
        }
