import datetime
import os
import tempfile
from email.message import Message
from unittest.mock import patch

import pytest
from services.email_parser import _extract_thread_id, _sanitize_nul, parse_eml
from services.exceptions import EmailParseError


def test_parse_eml_basic():
    eml_content = b"""Message-ID: <123@test.com>
From: test@test.com\x00
To: recipient@test.com
Subject: Hello\x00World
Date: Mon, 27 Apr 2026 10:00:00 +0000

This is a test email.\x00"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["message_id"] == "<123@test.com>"
        assert parsed["sender"] == "test@test.com"  # NUL removed
        assert parsed["subject"] == "HelloWorld"  # NUL removed
        assert "This is a test email." in parsed["body"]
        assert "\x00" not in parsed["body"]
    finally:
        os.unlink(temp_path)


def test_parse_eml_multipart_html_fallback():
    eml_content = b"""Message-ID: <multi@test.com>
From: multi@test.com
To: recipient@test.com
Subject: Multipart HTML
Date: Mon, 27 Apr 2026 10:00:00 +0000
Content-Type: multipart/alternative; boundary="boundary-string"

--boundary-string
Content-Type: text/html; charset="utf-8"

<p>This is HTML content</p>
--boundary-string--"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["body"] == "This is HTML content"
    finally:
        os.unlink(temp_path)


def test_parse_eml_strips_active_html_from_display_fields():
    eml_content = b"""Message-ID: <xss@test.com>
From: Attacker <attacker@example.com>
To: recipient@test.com
Subject: <img src=x onerror=alert('subject')>Launch
Date: Mon, 27 Apr 2026 10:00:00 +0000
Content-Type: text/html; charset="utf-8"

<html><body>Hello<script>alert('body')</script><img src=x onerror=alert('body')></body></html>"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["subject"] == "Launch"
        assert parsed["body"] == "Hello"
        assert "<" not in parsed["body"]
        assert "script" not in parsed["body"].lower()
        assert parsed["message_id"] == "<xss@test.com>"
        assert parsed["sender"] == "Attacker <attacker@example.com>"
    finally:
        os.unlink(temp_path)


def test_parse_eml_strips_active_html_from_address_display_fields():
    eml_content = b"""Message-ID: <headers@test.com>
From: "<img src=x onerror=alert(1)>" <attacker@example.com>
To: "<script>alert(1)</script>" <recipient@test.com>
Reply-To: "&lt;svg onload=alert(1)&gt;" <reply@test.com>
Subject: Header display safety
Date: Mon, 27 Apr 2026 10:00:00 +0000

Plain body"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["sender"] == "attacker@example.com"
        assert parsed["recipients"] == "recipient@test.com"
        assert parsed["reply_to"] == "reply@test.com"
    finally:
        os.unlink(temp_path)


def test_parse_eml_strips_active_html_from_attachment_display_fields():
    eml_content = b"""Message-ID: <attachment-xss@test.com>
From: sender@test.com
To: recipient@test.com
Subject: Attachment display safety
Date: Mon, 27 Apr 2026 10:00:00 +0000
Content-Type: multipart/mixed; boundary="mixed-boundary"

--mixed-boundary
Content-Type: text/plain; charset="utf-8"

See attached.
--mixed-boundary
Content-Type: text/plain; charset="utf-8"
Content-Disposition: attachment; filename="<img src=x onerror=alert(1)>.txt"

<script>alert(1)</script>report
--mixed-boundary--"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["attachments"] == [{"filename": ".txt", "content": "report"}]
    finally:
        os.unlink(temp_path)


def test_parse_eml_missing_and_malformed_date():
    eml_content1 = b"""Message-ID: <nodate@test.com>
From: test@test.com
To: recipient@test.com
Subject: No Date

Test."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content1)
        temp_path1 = f.name

    eml_content2 = b"""Message-ID: <baddate@test.com>
From: test@test.com
To: recipient@test.com
Subject: Bad Date
Date: Invalid-Date-Format

Test."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content2)
        temp_path2 = f.name

    try:
        # Missing date
        parsed1 = parse_eml(temp_path1)
        assert isinstance(parsed1["date"], datetime.datetime)

        # Malformed date
        parsed2 = parse_eml(temp_path2)
        assert isinstance(parsed2["date"], datetime.datetime)
    finally:
        os.unlink(temp_path1)
        os.unlink(temp_path2)


def test_parse_eml_io_error():
    with pytest.raises(EmailParseError):
        parse_eml("/path/to/nonexistent/file.eml")


def test_parse_eml_thread_id():
    # 1. Has References
    eml1 = b"""Message-ID: <msg1@test.com>
References: <ref1@test.com> <ref2@test.com>
From: test@test.com
To: user@test.com
Subject: Test

Test"""
    # 2. No References, has In-Reply-To
    eml2 = b"""Message-ID: <msg2@test.com>
In-Reply-To: <ref3@test.com>
From: test@test.com
To: user@test.com
Subject: Test

Test"""
    # 3. Neither -> use Message-ID
    eml3 = b"""Message-ID: <msg3@test.com>
From: test@test.com
To: user@test.com
Subject: Test

Test"""

    for i, content in enumerate([eml1, eml2, eml3]):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
            f.write(content)
            temp_path = f.name
        try:
            parsed = parse_eml(temp_path)
            if i == 0:
                assert parsed["thread_id"] == "<ref1@test.com>"
            elif i == 1:
                assert parsed["thread_id"] == "<ref3@test.com>"
            elif i == 2:
                assert parsed["thread_id"] == "<msg3@test.com>"
        finally:
            os.unlink(temp_path)


def test_extract_thread_id_uses_first_reference_from_long_header():
    msg = Message()
    msg["References"] = " ".join(
        ["<root@test.com>", *(f"<ref-{index}@test.com>" for index in range(200))]
    )
    msg["In-Reply-To"] = "<reply@test.com>"

    assert _extract_thread_id(msg, "<message@test.com>") == "<root@test.com>"


def test_parse_eml_extracts_reply_to_header():
    eml_content = b"""Message-ID: <reply-to@test.com>
From: Sender Name <sender@test.com>
Reply-To: Reply Target <reply-target@test.com>
To: user@test.com
Subject: Reply-To Test

Test"""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".eml") as f:
        f.write(eml_content)
        temp_path = f.name

    try:
        parsed = parse_eml(temp_path)
        assert parsed["reply_to"] == "Reply Target <reply-target@test.com>"
    finally:
        os.unlink(temp_path)

def test_parse_eml_mocked_oserror():
    with patch("builtins.open", side_effect=OSError("Mocked OS Error")):
        with pytest.raises(
            EmailParseError,
            match=r"Failed to read file dummy\.eml: Mocked OS Error",
        ):
            parse_eml("dummy.eml")


def test_sanitize_nul():
    # Normal string
    assert _sanitize_nul("hello world") == "hello world"

    # Strings with NUL characters
    assert _sanitize_nul("hello\x00world") == "helloworld"
    assert _sanitize_nul("\x00hello world") == "hello world"
    assert _sanitize_nul("hello world\x00") == "hello world"
    assert _sanitize_nul("hello\x00\x00world") == "helloworld"
    assert _sanitize_nul("\x00") == ""

    # Empty string
    assert _sanitize_nul("") == ""

    # None value
    assert _sanitize_nul(None) == ""

    # Non-string types (should be cast to string representations without NUL)
    assert _sanitize_nul(123) == "123"
    assert _sanitize_nul(12.3) == "12.3"
    assert _sanitize_nul(True) == "True"

def test_sanitize_display_text():
    from services.email_parser import _sanitize_display_text

    # Normal string
    assert _sanitize_display_text("hello world") == "hello world"

    # Strings with NUL characters
    assert _sanitize_display_text("hello\x00world") == "helloworld"

    # Strings with HTML tags
    assert _sanitize_display_text("<b>hello</b> world") == "hello world"
    assert _sanitize_display_text("<script>alert('xss')</script>") == ""
    assert _sanitize_display_text("hello <img src=x onerror=alert(1)>world") == "hello world"

    # Strings combining NUL and HTML
    assert _sanitize_display_text("<b>hello\x00</b>") == "hello"
    assert _sanitize_display_text("<script\x00>alert('xss')</script>") == ""
    # Let's see what happens exactly - _sanitize_nul strips NUL first, then strip_html_markup acts on the rest.
    # So "<script\x00>..." becomes "<script>..." and then strip_html_markup strips it.
    assert _sanitize_display_text("<script\x00>alert('xss\x00')</script>") == ""

    # Empty string
    assert _sanitize_display_text("") == ""

    # None value (falls back to _sanitize_nul which converts None to "")
    assert _sanitize_display_text(None) == ""
