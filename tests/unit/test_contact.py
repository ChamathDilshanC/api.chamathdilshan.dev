"""Public contact form: validation, abuse guards and the email sent through Resend."""

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.contact import routes as contact_routes
from app.core.config import settings
from app.integrations import resend
from app.integrations.resend import ContactMessage, EmailError
from tests.conftest import OWNER

VALID = {
    "firstName": "Jane",
    "lastName": "Perera",
    "email": "jane@company.com",
    "category": "Web app",
    "message": "Hello <b>there</b>\nSecond line",
}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[ContactMessage]:
    """Captures contact messages instead of emailing them."""
    messages: list[ContactMessage] = []

    async def fake_send(msg: ContactMessage) -> None:
        messages.append(msg)

    monkeypatch.setattr(contact_routes, "send_contact_message", fake_send)
    return messages


def test_valid_message_is_sent(client: TestClient, sent: list[ContactMessage]) -> None:
    res = client.post("/api/contact", json=VALID)
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True}
    assert "no-store" in res.headers["cache-control"]
    assert sent == [ContactMessage("Jane", "Perera", "jane@company.com", "Web app",
                                   "Hello <b>there</b>\nSecond line")]


def test_message_is_optional_and_fields_are_trimmed(
    client: TestClient, sent: list[ContactMessage]
) -> None:
    body = {**VALID, "firstName": "  Jane ", "message": ""}
    assert client.post("/api/contact", json=body).status_code == 200
    assert sent[0].first_name == "Jane"
    assert sent[0].message == ""


@pytest.mark.parametrize(
    "change",
    [
        {"firstName": ""},
        {"lastName": "   "},
        {"email": "not-an-email"},
        {"email": "jane@localhost"},
        {"email": "jane@company.com\nBcc: x@y.com"},
        {"category": ""},
        {"firstName": "Jane\r\nBcc: x@y.com"},
        {"message": "x" * 5001},
        {"extra": "field"},
    ],
)
def test_invalid_input_is_rejected(
    client: TestClient, sent: list[ContactMessage], change: dict[str, str]
) -> None:
    assert client.post("/api/contact", json={**VALID, **change}).status_code == 422
    assert sent == []


def test_honeypot_pretends_success_but_sends_nothing(
    client: TestClient, sent: list[ContactMessage]
) -> None:
    res = client.post("/api/contact", json={**VALID, "website": "https://spam.example"})
    assert res.status_code == 200
    assert sent == []


def test_other_origins_are_refused(client: TestClient, sent: list[ContactMessage]) -> None:
    res = client.post("/api/contact", json=VALID, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert sent == []


def test_visitors_are_rate_limited(
    client: TestClient, sent: list[ContactMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_CONTACT_PER_HOUR", 2)
    assert client.post("/api/contact", json=VALID).status_code == 200
    assert client.post("/api/contact", json=VALID).status_code == 200
    blocked = client.post("/api/contact", json=VALID)
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers
    # Behind Vercel, each visitor is keyed by the address its edge reports.
    other = client.post("/api/contact", json=VALID,
                        headers={"x-vercel-forwarded-for": "203.0.113.9"})
    assert other.status_code == 200
    assert len(sent) == 3


def test_email_failure_is_a_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(msg: ContactMessage) -> None:
        raise EmailError("Resend responded 500")

    monkeypatch.setattr(contact_routes, "send_contact_message", broken)
    res = client.post("/api/contact", json=VALID)
    assert res.status_code == 502
    assert "could not be sent" in res.json()["detail"]


# --- the email itself ---------------------------------------------------------


@pytest.fixture
def resend_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Records what would be posted to Resend."""
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        calls.append({"auth": request.headers["authorization"], **json.loads(request.content)})
        return httpx.Response(200, json={"id": "email_1"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        resend.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "RESEND_FROM", "Chamath Dilshan <auth@chamathdilshan.com>")
    monkeypatch.setattr(settings, "PUBLIC_SITE_URL", "https://www.chamathdilshan.com")
    monkeypatch.setattr(settings, "CONTACT_TO", "")
    return calls


async def test_email_goes_to_the_owner_with_reply_to_the_visitor(
    resend_calls: list[dict[str, Any]],
) -> None:
    await resend.send_contact_message(
        ContactMessage("Jane", 'Pe"rera', "jane@company.com", "Web app", "Hi <script>")
    )
    [call] = resend_calls
    assert call["auth"] == "Bearer re_test"
    assert call["to"] == [OWNER]
    assert call["reply_to"] == "jane@company.com"
    assert call["from"] == '"Jane Perera via chamathdilshan.com" <auth@chamathdilshan.com>'
    assert call["subject"] == 'Web app enquiry from Jane Pe"rera'
    assert "Hi <script>" in call["text"]
    assert "Hi &lt;script&gt;" in call["html"]
    assert "<script>" not in call["html"]


async def test_contact_to_overrides_the_owner(
    resend_calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CONTACT_TO", "Inbox@Example.com")
    await resend.send_contact_message(ContactMessage("A", "B", "a@b.co", "Other", ""))
    assert resend_calls[0]["to"] == ["inbox@example.com"]
    assert "(No message)" in resend_calls[0]["text"]


async def test_missing_api_key_fails_outside_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    with pytest.raises(EmailError):
        await resend.send_contact_message(ContactMessage("A", "B", "a@b.co", "Other", ""))
