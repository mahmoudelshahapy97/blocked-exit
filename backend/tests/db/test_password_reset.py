"""Password reset by emailed code: request, reset, and the rules that keep the
code from being guessed, replayed or used to find accounts.

Mail never leaves the process: aiosmtplib.send is replaced by a fake that keeps
what would have been sent.
"""

from __future__ import annotations

import re

import aiosmtplib
import pytest

from app.core.config import settings
from tests.db.conftest import PASSWORD, bearer, login

NEW_PASSWORD = "Fresh-Password-42"


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    async def fake_send(message, **kwargs):
        sent.append(message)

    monkeypatch.setattr(aiosmtplib, "send", fake_send)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    return sent


def _code_from(message) -> str:
    body = message.get_body(preferencelist=("plain",)).get_content()
    return re.search(r"code is (\d{6})", body).group(1)


async def _request_code(client, email: str):
    response = await client.post("/auth/forgot-password", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()["message"]


async def _reset(client, email: str, code: str, password: str = NEW_PASSWORD):
    return await client.post(
        "/auth/reset-password",
        json={"email": email, "code": code, "new_password": password},
    )


# -- availability ----------------------------------------------------------------
async def test_off_without_smtp(client, superadmin):
    assert (await client.get("/auth/bootstrap")).json()["password_reset"] is False
    response = await client.post(
        "/auth/forgot-password", json={"email": "root@example.com"}
    )
    assert response.status_code == 503
    assert response.json()["error"] == "not_configured"
    assert (await _reset(client, "root@example.com", "123456")).status_code == 503


async def test_bootstrap_offers_it_once_smtp_is_set(client, outbox):
    assert (await client.get("/auth/bootstrap")).json()["password_reset"] is True


# -- the happy path ----------------------------------------------------------------
async def test_code_resets_the_password_and_signs_out_everywhere(
    client, make_user, outbox
):
    token = await make_user("bob")

    await _request_code(client, "Bob@Example.com")
    assert len(outbox) == 1
    assert outbox[0]["To"] == "bob@example.com"
    code = _code_from(outbox[0])

    response = await _reset(client, "bob@example.com", code)
    assert response.status_code == 200, response.text

    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401
    assert await login(client, "bob", NEW_PASSWORD)
    old = await client.post("/auth/login", json={"username": "bob", "password": PASSWORD})
    assert old.status_code == 401


async def test_code_works_once(client, make_user, outbox):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    code = _code_from(outbox[0])

    assert (await _reset(client, "bob@example.com", code)).status_code == 200
    again = await _reset(client, "bob@example.com", code, "Another-Pass-77")
    assert again.status_code == 400
    assert await login(client, "bob", NEW_PASSWORD)


async def test_only_a_hash_is_stored(client, make_user, outbox, sql):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    code = _code_from(outbox[0])

    stored = await sql.fetchval("SELECT otp_hash FROM password_otp")
    assert stored and code not in stored


# -- no account oracle -------------------------------------------------------------
async def test_unknown_and_deactivated_accounts_get_the_same_answer(
    client, superadmin, make_user, outbox
):
    await make_user("bob")
    known = await _request_code(client, "bob@example.com")
    assert len(outbox) == 1

    assert await _request_code(client, "nobody@example.com") == known
    assert await _request_code(client, "not an email") == known

    await make_user("carol")
    users = (await client.get("/auth/users", headers=bearer(superadmin))).json()
    carol = next(u for u in users if u["username"] == "carol")
    await client.patch(
        f"/auth/users/{carol['id']}",
        json={"is_active": False},
        headers=bearer(superadmin),
    )
    assert await _request_code(client, "carol@example.com") == known
    assert len(outbox) == 1


async def test_wrong_code_and_unknown_account_are_rejected_alike(
    client, make_user, outbox
):
    await make_user("bob")
    await _request_code(client, "bob@example.com")

    wrong = await _reset(client, "bob@example.com", "000000")
    unknown = await _reset(client, "nobody@example.com", "000000")
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json()


# -- guessing and replay ---------------------------------------------------------
async def test_too_many_wrong_guesses_burn_the_code(client, make_user, outbox):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    code = _code_from(outbox[0])
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        assert (await _reset(client, "bob@example.com", wrong)).status_code == 400
    assert (await _reset(client, "bob@example.com", code)).status_code == 400


async def test_expired_code_is_rejected(client, make_user, outbox, sql):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    code = _code_from(outbox[0])

    await sql.execute("UPDATE password_otp SET expires_at = now() - interval '1 second'")
    assert (await _reset(client, "bob@example.com", code)).status_code == 400
    assert await sql.fetchval("SELECT count(*) FROM password_otp") == 0


async def test_resend_window_then_only_the_newest_code_works(
    client, make_user, outbox, monkeypatch
):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    await _request_code(client, "bob@example.com")
    assert len(outbox) == 1, "a second code inside the resend window"

    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
    await _request_code(client, "bob@example.com")
    assert len(outbox) == 2
    first, second = _code_from(outbox[0]), _code_from(outbox[1])

    if first != second:
        assert (await _reset(client, "bob@example.com", first)).status_code == 400
    assert (await _reset(client, "bob@example.com", second)).status_code == 200


async def test_a_weak_new_password_does_not_spend_the_code(client, make_user, outbox):
    await make_user("bob")
    await _request_code(client, "bob@example.com")
    code = _code_from(outbox[0])

    assert (await _reset(client, "bob@example.com", code, "short")).status_code == 422
    assert (await _reset(client, "bob@example.com", code)).status_code == 200


async def test_reset_also_kills_refresh_tokens_and_allows_an_immediate_login(
    client, make_user, outbox
):
    await make_user("bob")
    pair = (
        await client.post("/auth/login", json={"username": "bob", "password": PASSWORD})
    ).json()
    await _request_code(client, "bob@example.com")
    reset = await _reset(client, "bob@example.com", _code_from(outbox[0]))
    assert reset.status_code == 200

    refreshed = await client.post(
        "/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    assert refreshed.status_code == 401

    # Same second as the cutoff: the new session must still work.
    token = await login(client, "bob", NEW_PASSWORD)
    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 200
