"""Alert gating and delivery.

The policy decides *whether* to alert; dispatch decides *how* and records the
outcome. Neither may ever raise into the detection pipeline — a dead SMTP
server must not stop an exit being monitored.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.enums import AlertChannel, AlertStatus, BlockageState
from app.services import alerting
from app.services.alerting import AlertPolicy, build_payload


@pytest.fixture(autouse=True)
def alerts_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", True)


def make_policy(min_duration: float = 10.0, cooldown: float = 300.0) -> AlertPolicy:
    return AlertPolicy(min_duration_s=min_duration, cooldown_s=cooldown)


# -- the duration gate ----------------------------------------------------
def test_a_brief_blockage_does_not_alert():
    policy = make_policy(min_duration=10.0)
    assert not policy.should_alert(
        state=BlockageState.FULL, duration_s=4.0, now=100.0
    )


def test_alerting_once_the_blockage_has_persisted():
    policy = make_policy(min_duration=10.0)
    assert policy.should_alert(state=BlockageState.FULL, duration_s=11.0, now=100.0)


def test_a_clear_exit_never_alerts():
    policy = make_policy(min_duration=0.0)
    assert not policy.should_alert(
        state=BlockageState.CLEAR, duration_s=999.0, now=100.0
    )


def test_alerts_disabled_globally_silences_everything(monkeypatch):
    monkeypatch.setattr(settings, "ALERTS_ENABLED", False)
    policy = make_policy(min_duration=0.0)
    assert not policy.should_alert(
        state=BlockageState.FULL, duration_s=999.0, now=100.0
    )


# -- cooldown -------------------------------------------------------------
def test_cooldown_suppresses_a_repeat_at_the_same_severity():
    policy = make_policy(min_duration=10.0, cooldown=300.0)
    assert policy.should_alert(state=BlockageState.PARTIAL, duration_s=20.0, now=0.0)
    policy.mark_sent(state=BlockageState.PARTIAL, now=0.0)

    assert not policy.should_alert(
        state=BlockageState.PARTIAL, duration_s=100.0, now=120.0
    )


def test_the_next_alert_is_allowed_once_the_cooldown_expires():
    policy = make_policy(min_duration=10.0, cooldown=300.0)
    policy.mark_sent(state=BlockageState.PARTIAL, now=0.0)
    assert policy.should_alert(
        state=BlockageState.PARTIAL, duration_s=400.0, now=301.0
    )


def test_escalation_bypasses_the_cooldown():
    """A partial obstruction becoming total is news, whatever the cooldown says."""
    policy = make_policy(min_duration=10.0, cooldown=300.0)
    policy.mark_sent(state=BlockageState.PARTIAL, now=0.0)

    assert policy.should_alert(state=BlockageState.FULL, duration_s=30.0, now=10.0)


def test_de_escalation_does_not_bypass_the_cooldown():
    policy = make_policy(min_duration=10.0, cooldown=300.0)
    policy.mark_sent(state=BlockageState.FULL, now=0.0)
    assert not policy.should_alert(
        state=BlockageState.PARTIAL, duration_s=30.0, now=10.0
    )


def test_reset_forgets_the_cooldown():
    """A new event starts a new conversation."""
    policy = make_policy(min_duration=10.0, cooldown=300.0)
    policy.mark_sent(state=BlockageState.FULL, now=0.0)
    policy.reset()
    assert policy.should_alert(state=BlockageState.FULL, duration_s=20.0, now=5.0)


# -- payload --------------------------------------------------------------
def test_payload_carries_the_full_picture():
    payload = build_payload(
        camera_id=1,
        camera_name="Exit A",
        location="Floor 1",
        state=BlockageState.PARTIAL,
        accessibility_pct=61.234,
        blocked_duration_s=42.57,
        risk_score=47.7,
        risk_level="MEDIUM",
        recommended_action="Inspect the exit",
        blocking_objects=[{"label": "chair", "area_pct": 38.8}],
        strategy="zone_based",
        event_id=7,
    )
    assert payload["blocked"] is True
    assert payload["accessibility_pct"] == 61.23
    assert payload["blocked_duration_s"] == 42.6  # rounded to 0.1s
    assert payload["event_id"] == 7
    assert payload["occurred_at"].endswith("+00:00")


# -- channel selection ----------------------------------------------------
def test_no_configured_channel_means_nothing_is_sent(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert alerting._configured_channels() == []


def test_email_needs_both_a_host_and_a_recipient(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", None)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", [])
    assert alerting._configured_channels() == []

    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", ["ops@test"])
    assert alerting._configured_channels() == [AlertChannel.EMAIL]


# -- dispatch -------------------------------------------------------------
async def test_dispatch_without_channels_returns_nothing(monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_URL", None)
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert await alerting.dispatch({"state": "FULL"}, workspace_id=1, camera_id=1) == []


async def test_a_failing_channel_is_recorded_not_raised(monkeypatch):
    """The pipeline keeps running even when every delivery route is broken."""
    recorded: list = []

    async def boom(channel, payload, snapshot, recipients=None):
        raise RuntimeError("smtp is on fire")

    class FakeSession:
        def add(self, row):
            recorded.append(row)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class FakeScope:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(alerting, "_deliver", boom)
    monkeypatch.setattr(alerting, "session_scope", lambda: FakeScope())

    rows = await alerting.dispatch(
        {"state": "FULL"}, workspace_id=1, camera_id=1, channels=[AlertChannel.WEBHOOK]
    )

    assert len(rows) == 1
    assert rows[0].status == AlertStatus.FAILED.value
    assert "smtp is on fire" in rows[0].error
    assert rows[0].sent_at is None
