"""Pytest configuration.

Tests must not touch a real database or download weights, so the environment is
neutralised before ``app.core.config`` is imported anywhere.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("AUTO_CREATE_TABLES", "false")
os.environ.setdefault("ALERTS_ENABLED", "true")
os.environ.setdefault("DEVICE", "cpu")
# 32+ chars and not the published dev default, so `app.core.config` imports
# without the production guard's SECRET_KEY complaint ever entering into it —
# these are ENV=development settings, that guard does not even run here.
os.environ.setdefault(
    "SECRET_KEY", "pytest-only-secret-key-never-used-outside-the-test-suite"
)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test client looks like one address; the sign-in and reset limits
    must not carry over from one test to the next."""
    from app.api.routes import auth

    auth.login_failures._hits.clear()
    auth.reset_requests._hits.clear()
