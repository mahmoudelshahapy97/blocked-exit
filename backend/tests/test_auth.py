"""Password hashing and JWT lifecycle: everything in app.core.security that
needs no database. Revocation bookkeeping, tenancy resolution and the full
signup/login/refresh round-trip need a real Postgres and belong in an
integration suite — see the plan's tenancy verification steps.
"""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core import security
from app.core.enums import TokenType, WorkspaceRole
from app.core.security import TokenError
from app.utils.timing import utcnow


# -- passwords ----------------------------------------------------------------
def test_hash_round_trips():
    hashed = security.hash_password("correct horse battery staple")
    assert security.verify_password("correct horse battery staple", hashed)


def test_wrong_password_fails():
    hashed = security.hash_password("correct horse battery staple")
    assert not security.verify_password("wrong password", hashed)


def test_two_hashes_of_the_same_password_differ():
    """argon2 salts per call — equal hashes would mean a lookup table works."""
    a = security.hash_password("same password")
    b = security.hash_password("same password")
    assert a != b
    assert security.verify_password("same password", a)
    assert security.verify_password("same password", b)


@pytest.mark.parametrize("bad_hash", ["", None, "not-a-real-hash", "$argon2id$garbage"])
def test_verify_never_raises_on_a_corrupt_or_missing_hash(bad_hash):
    """A stored hash that is empty or malformed must fail closed, not 500 —
    an attacker should not be able to tell a corrupt row from a wrong password."""
    assert security.verify_password("anything", bad_hash) is False


def test_needs_rehash_is_true_for_junk():
    assert security.needs_rehash("not-a-real-hash") is True


def test_needs_rehash_is_false_right_after_hashing():
    assert security.needs_rehash(security.hash_password("x")) is False


# -- tokens ---------------------------------------------------------------------
def test_create_and_decode_access_token():
    token, jti, expires_at = security.create_token(
        user_id=42, workspace_id=7, token_type=TokenType.ACCESS, role="user"
    )
    claims = security.decode_token(token, expected_type=TokenType.ACCESS)

    assert claims["sub"] == "42"
    assert claims["workspace_id"] == 7
    assert claims["token_type"] == "access"
    assert claims["jti"] == jti
    assert expires_at > utcnow()


def test_refresh_token_has_a_longer_lifetime_than_access():
    _, _, access_exp = security.create_token(
        user_id=1, workspace_id=None, token_type=TokenType.ACCESS
    )
    _, _, refresh_exp = security.create_token(
        user_id=1, workspace_id=None, token_type=TokenType.REFRESH
    )
    assert refresh_exp > access_exp


def test_decode_rejects_the_wrong_expected_type():
    token, _, _ = security.create_token(
        user_id=1, workspace_id=None, token_type=TokenType.ACCESS
    )
    with pytest.raises(TokenError, match="refresh"):
        security.decode_token(token, expected_type=TokenType.REFRESH)


def test_decode_rejects_a_malformed_token():
    with pytest.raises(TokenError):
        security.decode_token("not-a-jwt-at-all")


def test_decode_rejects_an_empty_token():
    with pytest.raises(TokenError):
        security.decode_token("")


def test_decode_rejects_an_expired_token(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token, _, _ = security.create_token(
        user_id=1, workspace_id=None, token_type=TokenType.ACCESS
    )
    with pytest.raises(TokenError, match="expired"):
        security.decode_token(token, expected_type=TokenType.ACCESS)


def test_decode_rejects_a_tampered_signature():
    token, _, _ = security.create_token(
        user_id=1, workspace_id=None, token_type=TokenType.ACCESS
    )
    tampered = token[:-4] + ("0" if token[-1] != "0" else "1") + token[-3:]
    with pytest.raises(TokenError):
        security.decode_token(tampered)


def test_decode_rejects_a_token_signed_with_a_different_key():
    from app.core.config import settings

    forged = jwt.encode(
        {
            "sub": "1",
            "jti": "forged",
            "token_type": "access",
            "exp": utcnow() + timedelta(minutes=5),
        },
        "a-completely-different-signing-key",
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(TokenError):
        security.decode_token(forged)


def test_stream_ticket_is_scoped_to_one_camera_and_short_lived():
    ticket, expires_at = security.create_stream_ticket(
        user_id=1, workspace_id=2, camera_id=99
    )
    claims = security.decode_token(ticket, expected_type=TokenType.STREAM)

    assert claims["camera_id"] == 99
    assert claims["workspace_id"] == 2
    assert (expires_at - utcnow()) <= timedelta(seconds=security.STREAM_TICKET_LIFETIME_S)


def test_stream_ticket_is_rejected_as_an_access_token():
    """A stream ticket must not double as a general-purpose credential."""
    ticket, _ = security.create_stream_ticket(user_id=1, workspace_id=2, camera_id=99)
    with pytest.raises(TokenError, match="access"):
        security.decode_token(ticket, expected_type=TokenType.ACCESS)


# -- workspace role ranking -----------------------------------------------------
def test_workspace_role_rank_is_ordered():
    assert WorkspaceRole.VIEWER.rank < WorkspaceRole.MEMBER.rank
    assert WorkspaceRole.MEMBER.rank < WorkspaceRole.ADMIN.rank


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        (WorkspaceRole.ADMIN, WorkspaceRole.VIEWER, True),
        (WorkspaceRole.ADMIN, WorkspaceRole.ADMIN, True),
        (WorkspaceRole.VIEWER, WorkspaceRole.MEMBER, False),
        (WorkspaceRole.MEMBER, WorkspaceRole.MEMBER, True),
        (WorkspaceRole.MEMBER, WorkspaceRole.ADMIN, False),
    ],
)
def test_can_act_as(actual: WorkspaceRole, required: WorkspaceRole, expected: bool):
    assert actual.can_act_as(required) is expected
