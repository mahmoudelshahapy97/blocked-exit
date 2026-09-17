"""Keep stream credentials out of logs and error bodies.

RTSP sources are routinely written as ``rtsp://user:password@host/path``. That
string reaches a log line on every reconnect attempt and an error body on every
failed calibration, so without redaction a camera password ends up in the
container log, the log shipper, and whatever the client does with a 422.

Stored and API-returned URLs are left intact — the configuration UI has to show
an operator what was entered.
"""

from __future__ import annotations

import re

__all__ = ["redact_url", "redact_text"]

# scheme://[user[:password]@]rest — the userinfo is everything we must hide.
_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][\w+.-]*://)(?P<userinfo>[^/@\s]+)@")
_MASK = "***:***"


def redact_url(url: str | None) -> str:
    """Replace any embedded credentials with a fixed mask.

    Non-URL input and URLs without credentials are returned unchanged, so this
    is always safe to wrap around a value on its way into a log call.
    """
    if not url:
        return ""
    return _USERINFO.sub(rf"\g<scheme>{_MASK}@", url)


def redact_text(text: str | None) -> str:
    """Redact every URL embedded in a longer message (exception strings, etc.)."""
    if not text:
        return ""
    return _USERINFO.sub(rf"\g<scheme>{_MASK}@", text)
