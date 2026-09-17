"""Settings parsing and the production guard.

Settings are built directly here rather than through `get_settings()` so each
case is isolated from the process environment and the lru_cache.
"""

from __future__ import annotations

import warnings

import pytest

from app.core.config import DEV_SECRET_KEY, Settings

# Never read the developer's real .env while asserting on defaults.
BASE = {"_env_file": None}
# Long enough (32+ chars) and not the published default, so tests that
# are not specifically about SECRET_KEY don't trip that guard too.
VALID_SECRET = "test-suite-secret-key-not-the-published-default-value"


def make(**overrides) -> Settings:
    return Settings(**BASE, **overrides)


# -- CSV parsing ----------------------------------------------------------
def test_plain_csv_origins_are_split():
    assert make(CORS_ORIGINS="https://a.test, https://b.test").CORS_ORIGINS == [
        "https://a.test",
        "https://b.test",
    ]


def test_json_list_origins_still_work():
    assert make(CORS_ORIGINS='["https://a.test"]').CORS_ORIGINS == ["https://a.test"]


def test_empty_csv_is_an_empty_list():
    assert make(ALERT_EMAIL_TO="").ALERT_EMAIL_TO == []


def test_obstacle_classes_parse_as_ints():
    assert make(OBSTACLE_CLASSES="0, 56, 57").OBSTACLE_CLASSES == [0, 56, 57]


# -- production guard -----------------------------------------------------
def test_production_refuses_auto_create_tables():
    with pytest.raises(ValueError, match="AUTO_CREATE_TABLES"):
        make(ENV="production", DEBUG=False, AUTO_CREATE_TABLES=True)


def test_production_refuses_debug():
    with pytest.raises(ValueError, match="DEBUG"):
        make(ENV="production", DEBUG=True, AUTO_CREATE_TABLES=False)


def test_both_problems_are_reported_together():
    """One restart should reveal every blocker, not the first one only."""
    with pytest.raises(ValueError) as exc:
        make(ENV="production", DEBUG=True, AUTO_CREATE_TABLES=True)
    assert "AUTO_CREATE_TABLES" in str(exc.value)
    assert "DEBUG" in str(exc.value)


def test_development_defaults_are_left_alone():
    settings = make(ENV="development", DEBUG=True, AUTO_CREATE_TABLES=True)
    assert settings.AUTO_CREATE_TABLES is True
    assert not settings.is_production


@pytest.mark.parametrize("value", ["production", "PRODUCTION", " prod "])
def test_production_is_recognised_however_it_is_spelled(value: str):
    with pytest.raises(ValueError):
        make(ENV=value, DEBUG=True, AUTO_CREATE_TABLES=False)


def test_wildcard_cors_warns_rather_than_blocks():
    """An operator may have a reason; refusing to boot over CORS would be worse."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        settings = make(
            ENV="production",
            DEBUG=False,
            AUTO_CREATE_TABLES=False,
            CORS_ORIGINS="*",
            SECRET_KEY=VALID_SECRET,
        )
    assert settings.CORS_ORIGINS == ["*"]
    assert any("CORS_ORIGINS" in str(w.message) for w in caught)


def test_production_refuses_the_published_dev_secret_key():
    """The default SECRET_KEY is a literal in this file's source -- shipping it
    means anyone can mint themselves an admin token. Passed explicitly (rather
    than just omitted) so the test is not at the mercy of a SECRET_KEY the test
    runner's own environment happens to export."""
    with pytest.raises(ValueError, match="SECRET_KEY"):
        make(
            ENV="production",
            DEBUG=False,
            AUTO_CREATE_TABLES=False,
            SECRET_KEY=DEV_SECRET_KEY,
        )


def test_production_refuses_a_short_secret_key():
    with pytest.raises(ValueError, match="SECRET_KEY"):
        make(
            ENV="production",
            DEBUG=False,
            AUTO_CREATE_TABLES=False,
            SECRET_KEY="too-short",
        )


def test_production_accepts_a_proper_secret_key():
    settings = make(
        ENV="production",
        DEBUG=False,
        AUTO_CREATE_TABLES=False,
        CORS_ORIGINS="https://a.test",
        SECRET_KEY=VALID_SECRET,
    )
    assert settings.SECRET_KEY == VALID_SECRET


# -- derived properties ---------------------------------------------------
def test_credentials_are_disabled_for_wildcard_cors():
    """Browsers reject `Allow-Origin: *` with credentials, so never claim both."""
    assert make(CORS_ORIGINS="*").cors_allow_credentials is False
    assert make(CORS_ORIGINS="https://a.test").cors_allow_credentials is True


def test_docs_are_off_in_production_unless_asked_for():
    common = {"DEBUG": False, "AUTO_CREATE_TABLES": False, "SECRET_KEY": VALID_SECRET}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert make(ENV="production", **common).docs_enabled is False
        assert make(ENV="production", ENABLE_DOCS=True, **common).docs_enabled is True
    assert make(ENV="development").docs_enabled is True
    assert make(ENV="development", ENABLE_DOCS=False).docs_enabled is False


def test_process_interval_handles_zero_fps():
    assert make(PROCESS_FPS=0).process_interval_s == 0.0
    assert make(PROCESS_FPS=4).process_interval_s == 0.25
