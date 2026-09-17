"""Risk scoring bands and alert gating."""

from __future__ import annotations

from app.core.enums import BlockageState, RiskLevel
from app.schemas.detection import BlockingObject
from app.services import risk
from app.services.alerting import AlertPolicy


def obj(label: str, area_pct: float = 50.0) -> BlockingObject:
    return BlockingObject(label=label, confidence=0.9, area_pct=area_pct)


def test_clear_exit_scores_zero():
    assessment = risk.assess(
        state=BlockageState.CLEAR,
        accessibility_pct=100.0,
        blocked_duration_s=0.0,
    )
    assert assessment.score == 0.0
    assert assessment.level is RiskLevel.LOW


def test_fully_blocked_for_a_long_time_is_critical():
    assessment = risk.assess(
        state=BlockageState.FULL,
        accessibility_pct=5.0,
        blocked_duration_s=300.0,
        blocking_objects=[obj("couch")],
        people_count=4,
    )
    assert assessment.level is RiskLevel.CRITICAL
    assert assessment.recommended_action == "Clear Exit Immediately"


def test_a_blocked_exit_never_reports_low_risk():
    """An alert must not say "blocked" and "no action required" at once."""
    assessment = risk.assess(
        state=BlockageState.PARTIAL,
        accessibility_pct=94.0,
        blocked_duration_s=2.0,
        blocking_objects=[obj("person", area_pct=2.0)],
    )
    assert assessment.score < 30  # genuinely a minor obstruction
    assert assessment.level is RiskLevel.MEDIUM
    assert assessment.recommended_action != "No action required"


def test_duration_increases_the_score():
    common = {
        "state": BlockageState.PARTIAL,
        "accessibility_pct": 60.0,
        "blocking_objects": [obj("chair")],
    }
    brief = risk.assess(blocked_duration_s=5.0, **common)
    sustained = risk.assess(blocked_duration_s=120.0, **common)
    assert sustained.score > brief.score


def test_immovable_obstacle_outranks_a_person():
    common = {
        "state": BlockageState.PARTIAL,
        "accessibility_pct": 60.0,
        "blocked_duration_s": 20.0,
    }
    person = risk.assess(blocking_objects=[obj("person")], **common)
    furniture = risk.assess(blocking_objects=[obj("refrigerator")], **common)
    assert furniture.score > person.score


def test_score_never_exceeds_one_hundred():
    assessment = risk.assess(
        state=BlockageState.FULL,
        accessibility_pct=0.0,
        blocked_duration_s=10_000.0,
        blocking_objects=[obj("refrigerator")],
        people_count=50,
    )
    assert assessment.score <= 100.0


def test_alert_policy_waits_for_the_minimum_duration():
    policy = AlertPolicy(min_duration_s=10.0, cooldown_s=300.0)
    assert not policy.should_alert(state=BlockageState.FULL, duration_s=4.0, now=0.0)
    assert policy.should_alert(state=BlockageState.FULL, duration_s=12.0, now=0.0)


def test_alert_policy_respects_cooldown():
    policy = AlertPolicy(min_duration_s=10.0, cooldown_s=300.0)
    assert policy.should_alert(state=BlockageState.PARTIAL, duration_s=15.0, now=0.0)
    policy.mark_sent(state=BlockageState.PARTIAL, now=0.0)

    assert not policy.should_alert(
        state=BlockageState.PARTIAL, duration_s=60.0, now=100.0
    )
    assert policy.should_alert(state=BlockageState.PARTIAL, duration_s=60.0, now=400.0)


def test_escalation_bypasses_cooldown():
    policy = AlertPolicy(min_duration_s=10.0, cooldown_s=300.0)
    policy.mark_sent(state=BlockageState.PARTIAL, now=0.0)
    # PARTIAL -> FULL is worse news; it must not wait out the cooldown.
    assert policy.should_alert(state=BlockageState.FULL, duration_s=20.0, now=30.0)


def test_clear_state_never_alerts():
    policy = AlertPolicy(min_duration_s=0.0, cooldown_s=0.0)
    assert not policy.should_alert(
        state=BlockageState.CLEAR, duration_s=9999.0, now=0.0
    )
