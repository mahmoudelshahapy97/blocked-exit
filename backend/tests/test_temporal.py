"""Temporal filtering — the part that keeps passers-by from raising alarms."""

from __future__ import annotations

from app.core.enums import BlockageState
from app.services.temporal import TemporalFilter, TemporalTransition


class FakeClock:
    """Manual clock so tests never sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_filter(confirm: float = 5.0, clear: float = 3.0):
    clock = FakeClock()
    return (
        TemporalFilter(confirm_seconds=confirm, clear_seconds=clear, clock=clock),
        clock,
    )


def feed(
    filt: TemporalFilter,
    clock: FakeClock,
    state: BlockageState,
    seconds: float,
    step: float = 0.2,
) -> list[TemporalTransition]:
    """Simulate a worker observing `state` continuously for `seconds`."""
    transitions = []
    elapsed = 0.0
    while elapsed < seconds:
        transitions.append(filt.update(state))
        clock.advance(step)
        elapsed += step
    return transitions


def test_first_reading_is_adopted_immediately():
    filt, _ = make_filter()
    transition = filt.update(BlockageState.CLEAR)
    assert filt.state is BlockageState.CLEAR
    assert not transition.opened


def test_brief_obstruction_does_not_open_an_event():
    filt, clock = make_filter(confirm=5.0)
    filt.update(BlockageState.CLEAR)

    # Someone walks through the doorway for 2 seconds.
    transitions = feed(filt, clock, BlockageState.PARTIAL, seconds=2.0)

    assert not any(t.opened for t in transitions)
    assert filt.state is BlockageState.CLEAR
    assert not filt.blocked


def test_persistent_obstruction_opens_an_event_after_confirm_seconds():
    filt, clock = make_filter(confirm=5.0)
    filt.update(BlockageState.CLEAR)

    transitions = feed(filt, clock, BlockageState.PARTIAL, seconds=8.0)

    opened = [t for t in transitions if t.opened]
    assert len(opened) == 1  # exactly one open, not one per frame
    assert filt.state is BlockageState.PARTIAL
    assert filt.blocked


def test_escalation_is_reported_separately_from_opening():
    filt, clock = make_filter(confirm=2.0)
    filt.update(BlockageState.CLEAR)

    assert any(t.opened for t in feed(filt, clock, BlockageState.PARTIAL, 4.0))

    transitions = feed(filt, clock, BlockageState.FULL, 4.0)
    escalations = [t for t in transitions if t.escalated]
    assert len(escalations) == 1
    assert not any(t.opened for t in transitions)
    assert filt.state is BlockageState.FULL


def test_hysteresis_delays_the_return_to_clear():
    filt, clock = make_filter(confirm=2.0, clear=3.0)
    filt.update(BlockageState.CLEAR)
    feed(filt, clock, BlockageState.PARTIAL, 4.0)
    assert filt.blocked

    # A flicker of clear frames must not close the event.
    assert not any(t.closed for t in feed(filt, clock, BlockageState.CLEAR, 1.0))
    assert filt.blocked

    assert any(t.closed for t in feed(filt, clock, BlockageState.CLEAR, 4.0))
    assert not filt.blocked


def test_a_single_clear_frame_does_not_reset_the_confirmation():
    """A momentary gap in detection must not restart the whole countdown."""
    filt, clock = make_filter(confirm=3.0, clear=3.0)
    filt.update(BlockageState.CLEAR)

    feed(filt, clock, BlockageState.PARTIAL, 2.0)
    filt.update(BlockageState.CLEAR)  # one dropped detection
    clock.advance(0.2)
    transitions = feed(filt, clock, BlockageState.PARTIAL, 3.5)

    assert any(t.opened for t in transitions)


def test_duration_counts_from_when_the_obstruction_appeared():
    filt, clock = make_filter(confirm=2.0, clear=1.0)
    filt.update(BlockageState.CLEAR)

    appeared_at = clock.now
    feed(filt, clock, BlockageState.FULL, 30.0)

    # Includes the 2s confirmation window, not just the time since confirming.
    assert abs(filt.blocked_duration_s - (clock.now - appeared_at)) < 0.3

    cleared_at = clock.now
    transitions = feed(filt, clock, BlockageState.CLEAR, 3.0)
    closed = next(t for t in transitions if t.closed)

    # And it ends when the exit became usable, not when hysteresis expired.
    assert abs(closed.duration_s - (cleared_at - appeared_at)) < 0.3


def test_unknown_readings_hold_the_current_state():
    filt, clock = make_filter(confirm=1.0)
    filt.update(BlockageState.CLEAR)
    feed(filt, clock, BlockageState.FULL, 2.0)
    assert filt.state is BlockageState.FULL

    transition = filt.update(BlockageState.UNKNOWN)
    assert filt.state is BlockageState.FULL
    assert not transition.changed


def test_reset_clears_everything():
    filt, clock = make_filter(confirm=1.0)
    filt.update(BlockageState.CLEAR)
    feed(filt, clock, BlockageState.FULL, 2.0)

    filt.reset()
    assert filt.state is BlockageState.UNKNOWN
    assert not filt.blocked
    assert filt.blocked_duration_s == 0.0
