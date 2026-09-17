"""Temporal filtering.

A single frame showing a person in the doorway is not a blocked exit — someone
walking through is normal. This state machine only accepts a worse state once
it has held continuously for ``confirm_seconds``, and only returns to CLEAR
after ``clear_seconds`` of clear readings (hysteresis), so a flickering
detection cannot rattle the verdict.

Driven by an injectable clock so tests do not have to sleep.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.enums import BlockageState
from app.services.detector.base import CameraContext


@dataclass
class TemporalTransition:
    """What changed on this update, if anything."""

    opened: bool = False
    closed: bool = False
    escalated: bool = False
    previous_state: BlockageState = BlockageState.UNKNOWN
    state: BlockageState = BlockageState.UNKNOWN
    duration_s: float = 0.0

    @property
    def changed(self) -> bool:
        return self.opened or self.closed or self.escalated


@dataclass
class TemporalFilter:
    """Per-camera debounced blockage state."""

    confirm_seconds: float
    clear_seconds: float
    clock: Callable[[], float] = time.monotonic

    state: BlockageState = BlockageState.UNKNOWN
    _candidate: BlockageState = field(default=BlockageState.UNKNOWN, init=False)
    _candidate_since: float = field(default=0.0, init=False)
    _blocked_since: float | None = field(default=None, init=False)

    @classmethod
    def for_camera(
        cls, camera: CameraContext, clock: Callable[[], float] = time.monotonic
    ) -> TemporalFilter:
        return cls(
            confirm_seconds=camera.effective_confirm_seconds,
            clear_seconds=camera.effective_clear_seconds,
            clock=clock,
        )

    # -- state ------------------------------------------------------------
    @property
    def blocked(self) -> bool:
        return self.state.is_blocked()

    @property
    def blocked_duration_s(self) -> float:
        if self._blocked_since is None:
            return 0.0
        return max(0.0, self.clock() - self._blocked_since)

    def update(self, raw_state: BlockageState) -> TemporalTransition:
        """Feed one frame's raw verdict; return what (if anything) changed."""
        now = self.clock()
        previous = self.state

        if raw_state is BlockageState.UNKNOWN:
            # No usable reading — hold the current state rather than guessing.
            return TemporalTransition(previous_state=previous, state=previous)

        if raw_state != self._candidate:
            self._candidate = raw_state
            self._candidate_since = now

        held_for = now - self._candidate_since
        required = (
            self.clear_seconds
            if raw_state is BlockageState.CLEAR
            else self.confirm_seconds
        )

        if previous is BlockageState.UNKNOWN:
            # First reading: adopt it immediately so status is useful at once.
            required = 0.0

        if raw_state == previous or held_for < required:
            return TemporalTransition(
                previous_state=previous,
                state=previous,
                duration_s=self.blocked_duration_s,
            )

        # Confirmed transition.
        self.state = raw_state
        transition = TemporalTransition(previous_state=previous, state=raw_state)

        was_blocked = previous.is_blocked()
        now_blocked = raw_state.is_blocked()

        if now_blocked and not was_blocked:
            # Count from when the obstruction first appeared, not from when we
            # finished confirming it — otherwise every duration under-reports
            # by confirm_seconds.
            self._blocked_since = self._candidate_since
            transition.opened = True
        elif now_blocked and was_blocked:
            transition.escalated = raw_state.severity > previous.severity
        elif was_blocked and not now_blocked:
            transition.closed = True
            # Likewise the blockage ended when the exit became clear, not when
            # the hysteresis window expired. `is None` matters: a 0.0 timestamp
            # is a valid start time.
            started = (
                self._blocked_since
                if self._blocked_since is not None
                else self._candidate_since
            )
            transition.duration_s = max(0.0, self._candidate_since - started)
            self._blocked_since = None

        if transition.duration_s == 0.0:
            transition.duration_s = self.blocked_duration_s
        return transition

    def reset(self) -> None:
        self.state = BlockageState.UNKNOWN
        self._candidate = BlockageState.UNKNOWN
        self._candidate_since = 0.0
        self._blocked_since = None
