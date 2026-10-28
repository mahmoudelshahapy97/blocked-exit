"""One-time codes for "forgot your password?", mailed to the account's email.

After the platform's otp_service, with its holes closed. Checking the code and
setting the new password are one step, so a verified code is never a
free-standing "reset anything" pass, and the request never says whether an
account exists.

A code is 6 random digits, stored only as an HMAC (keyed with SECRET_KEY) in
``password_otp``, one row per account. It expires after ``OTP_TTL_SECONDS``, a
new one cannot be mailed within ``OTP_RESEND_SECONDS``, and
``OTP_MAX_ATTEMPTS`` wrong guesses burn it.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import secrets
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.user import PasswordOtp

logger = get_logger(__name__)

CODE_DIGITS = 6


def _hash(user_id: int, code: str) -> str:
    # The account id is in the MAC so a stored hash cannot be replayed for
    # another account.
    message = f"{user_id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


async def issue(session: AsyncSession, user_id: int) -> str | None:
    """A fresh code for the account, or None inside the resend window.

    Replaces any earlier code, so only the latest email works. Timestamps come
    from the database clock, the one every comparison below is made against.
    """
    code = new_code()
    stmt = insert(PasswordOtp).values(
        user_id=user_id,
        otp_hash=_hash(user_id, code),
        expires_at=func.now() + timedelta(seconds=settings.OTP_TTL_SECONDS),
        attempts=0,
        last_sent_at=func.now(),
    )
    # The WHERE on the conflict branch is the resend window: inside it the
    # existing row is left alone and nothing is returned.
    stmt = stmt.on_conflict_do_update(
        index_elements=[PasswordOtp.user_id],
        set_={
            "otp_hash": stmt.excluded.otp_hash,
            "expires_at": stmt.excluded.expires_at,
            "attempts": 0,
            "last_sent_at": stmt.excluded.last_sent_at,
        },
        where=PasswordOtp.last_sent_at
        <= func.now() - timedelta(seconds=settings.OTP_RESEND_SECONDS),
    ).returning(PasswordOtp.user_id)
    issued = await session.scalar(stmt)
    await session.commit()
    return code if issued is not None else None


async def consume(session: AsyncSession, user_id: int, code: str) -> bool:
    """True once for the right, unexpired code.

    On success the code is deleted but NOT committed, so the caller commits it
    together with the new password: either both happen or neither. Every
    failure commits on its own, because a wrong guess must count even though
    the request that made it fails.
    """
    # FOR UPDATE serialises concurrent guesses at one code, so N parallel
    # requests cannot all slip in under OTP_MAX_ATTEMPTS.
    row = (
        await session.execute(
            select(PasswordOtp, PasswordOtp.expires_at > func.now())
            .where(PasswordOtp.user_id == user_id)
            .with_for_update()
        )
    ).first()
    if row is None:
        await session.commit()
        return False
    otp, live = row

    if not live or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        await session.delete(otp)
        await session.commit()
        return False

    if hmac.compare_digest(otp.otp_hash, _hash(user_id, code.strip())):
        await session.delete(otp)
        await session.flush()
        return True

    otp.attempts += 1
    if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        await session.delete(otp)
    await session.commit()
    return False


# --- mail ------------------------------------------------------------------------
def _message(*, email: str, name: str, code: str) -> EmailMessage:
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    message = EmailMessage()
    message["Subject"] = f"{settings.APP_NAME}: your password reset code"
    message["From"] = settings.ALERT_EMAIL_FROM or (settings.SMTP_USER or "insighteye")
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\n"
        f"Your password reset code is {code}.\n"
        f"It expires in {minutes} minutes and works once.\n\n"
        "If you did not ask to reset your password, ignore this email; "
        "your password stays as it is.\n"
    )
    message.add_alternative(
        f"<p>Hello {html.escape(name)},</p>"
        "<p>Your password reset code is "
        f'<strong style="font-size:20px;letter-spacing:3px">{code}</strong>.<br>'
        f"It expires in {minutes} minutes and works once.</p>"
        "<p>If you did not ask to reset your password, ignore this email; "
        "your password stays as it is.</p>",
        subtype="html",
    )
    return message


async def send_code(*, user_id: int, email: str, name: str, code: str) -> None:
    """Mail the code. Runs as a background task, so failures are only logged.

    Takes plain values rather than the User row: the request's session is
    closed by the time a background task runs.
    """
    import aiosmtplib

    try:
        await aiosmtplib.send(
            _message(email=email, name=name, code=code),
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS,
            timeout=20,
        )
        logger.info("Password reset code mailed to user %s", user_id)
    except Exception as exc:
        logger.error(
            "Could not mail the password reset code to user %s: %s", user_id, exc
        )
