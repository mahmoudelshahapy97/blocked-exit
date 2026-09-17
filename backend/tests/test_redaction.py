"""Stream credentials must never reach a log line or an error body."""

from __future__ import annotations

import pytest

from app.core.redaction import redact_text, redact_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "rtsp://admin:hunter2@10.0.0.5:554/stream1",
            "rtsp://***:***@10.0.0.5:554/stream1",
        ),
        # A username with no password is still an identifier worth hiding.
        ("rtsp://operator@10.0.0.5:554/stream1", "rtsp://***:***@10.0.0.5:554/stream1"),
        ("http://user:pass@example.com/hook", "http://***:***@example.com/hook"),
        ("rtsps://a:b@host/path", "rtsps://***:***@host/path"),
    ],
)
def test_credentials_are_masked(raw: str, expected: str):
    assert redact_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "rtsp://10.0.0.5:554/stream1",
        "/videos/clip.mp4",
        "C:\\videos\\clip.mp4",
        "0",  # webcam index
        "",
    ],
)
def test_urls_without_credentials_are_untouched(raw: str):
    assert redact_url(raw) == raw


def test_none_becomes_empty_string():
    assert redact_url(None) == ""
    assert redact_text(None) == ""


def test_password_never_survives_anywhere_in_the_output():
    secret = "s3cr3t-p4ssw0rd"
    assert secret not in redact_url(f"rtsp://admin:{secret}@cam.local/1")


def test_redact_text_handles_a_url_embedded_in_a_message():
    message = (
        "Could not open video source: rtsp://admin:hunter2@10.0.0.5:554/s1 "
        "(connection refused)"
    )
    redacted = redact_text(message)
    assert "hunter2" not in redacted
    assert "connection refused" in redacted
    assert "10.0.0.5" in redacted  # the host is diagnostic, keep it


def test_query_string_credentials_are_left_alone():
    """Only userinfo is masked; a path or query is not assumed to be secret."""
    url = "http://example.com/hook?token=abc"
    assert redact_url(url) == url
