"""Transactional email through Resend (https://resend.com/docs/api-reference/emails/send-email)."""

import html
import logging
import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class EmailError(Exception):
    pass


def _code_email(code: str, minutes: int) -> tuple[str, str]:
    spaced = " ".join(code)
    text = (
        f"Your chamathdilshan.dev admin sign-in code is {code}.\n\n"
        f"It expires in {minutes} minutes. If you did not just sign in with Google, "
        "someone has your Google session: sign out of other devices and change your password."
    )
    card = "max-width:440px;background:#fff;border-radius:6px;padding:32px"
    digits = "font-size:34px;font-weight:600;letter-spacing:8px;font-family:Menlo,monospace"
    body = f"""<!doctype html>
<html><body style="margin:0;background:#f7f7f7;font-family:Inter,Arial,sans-serif;color:#000">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px">
    <tr><td align="center">
      <table role="presentation" width="100%" style="{card}">
        <tr><td style="font-size:13px;color:#666">chamathdilshan.dev · Admin</td></tr>
        <tr><td style="padding-top:24px;font-size:22px;font-weight:600;letter-spacing:-0.5px">
          Your sign-in code</td></tr>
        <tr><td style="padding-top:24px">
          <div style="{digits}">
            {html.escape(spaced)}</div></td></tr>
        <tr><td style="padding-top:24px;font-size:14px;line-height:1.5;color:#444">
          Enter this code to finish signing in. It expires in {minutes} minutes and works once.
        </td></tr>
        <tr><td style="padding-top:16px;font-size:12px;line-height:1.5;color:#888">
          Did not just sign in with Google? Someone has your Google session. Sign out of other
          devices and change your password.</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return text, body


async def send_login_code(to: str, code: str) -> None:
    """Email the one-time code. In development without an API key, log it instead."""
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    if not settings.RESEND_API_KEY:
        if settings.is_development:
            log.warning("RESEND_API_KEY is not set — development sign-in code for %s: %s", to, code)
            return
        raise EmailError("RESEND_API_KEY is not configured")

    text, body = _code_email(code, minutes)
    await _send(
        {
            "from": settings.RESEND_FROM,
            "to": [to],
            "subject": f"{code} is your admin sign-in code",
            "text": text,
            "html": body,
        }
    )


@dataclass(frozen=True)
class ContactMessage:
    first_name: str
    last_name: str
    email: str
    category: str
    message: str

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def _site_host() -> str:
    host = urlsplit(settings.PUBLIC_SITE_URL).hostname or "the website"
    return host.removeprefix("www.")


def _sender(name: str) -> str:
    """'"Jane Perera via example.com" <auth@example.com>': visitor's name, our own address."""
    address = parseaddr(settings.RESEND_FROM)[1] or settings.RESEND_FROM
    label = re.sub(r'[\x00-\x1f\x7f"<>\\]', "", f"{name} via {_site_host()}")[:80]
    return f'"{label}" <{address}>'


def _contact_email(msg: ContactMessage) -> tuple[str, str]:
    host = _site_host()
    message = msg.message or "(No message)"
    text = (
        f"New message from the contact form on {host}.\n\n"
        f"Name:     {msg.name}\n"
        f"Email:    {msg.email}\n"
        f"Category: {msg.category}\n\n"
        f"{message}\n\n"
        f"Reply to this email to answer {msg.first_name} directly."
    )
    e = html.escape
    card = "max-width:560px;background:#fff;border-radius:6px;padding:32px"
    label = "padding:4px 16px 4px 0;font-size:13px;color:#888;white-space:nowrap;vertical-align:top"
    value = "padding:4px 0;font-size:14px;color:#000"
    quote = (
        "margin-top:24px;padding:16px;border-left:3px solid #000;background:#f7f7f7;"
        "font-size:15px;line-height:1.6;white-space:pre-wrap;word-break:break-word"
    )
    body = f"""<!doctype html>
<html><body style="margin:0;background:#f7f7f7;font-family:Inter,Arial,sans-serif;color:#000">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px">
    <tr><td align="center">
      <table role="presentation" width="100%" style="{card}">
        <tr><td style="font-size:13px;color:#666">{e(host)} · Contact form</td></tr>
        <tr><td style="padding-top:24px;font-size:22px;font-weight:600;letter-spacing:-0.5px">
          {e(msg.category)} enquiry from {e(msg.name)}</td></tr>
        <tr><td style="padding-top:24px">
          <table role="presentation" cellpadding="0" cellspacing="0">
            <tr><td style="{label}">Name</td><td style="{value}">{e(msg.name)}</td></tr>
            <tr><td style="{label}">Email</td><td style="{value}">
              <a href="mailto:{e(msg.email)}" style="color:#000">{e(msg.email)}</a></td></tr>
            <tr><td style="{label}">Category</td><td style="{value}">{e(msg.category)}</td></tr>
          </table></td></tr>
        <tr><td><div style="{quote}">{e(message)}</div></td></tr>
        <tr><td style="padding-top:24px;font-size:12px;line-height:1.5;color:#888">
          Reply to this email to answer {e(msg.first_name)} directly.</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return text, body


async def send_contact_message(msg: ContactMessage) -> None:
    """Deliver a contact-form message to the owner; replies go straight to the visitor."""
    to = settings.contact_to
    if not to:
        raise EmailError("CONTACT_TO / ADMIN_EMAIL is not configured")
    if not settings.RESEND_API_KEY:
        if settings.is_development:
            log.warning("RESEND_API_KEY is not set — development contact message: %s", msg)
            return
        raise EmailError("RESEND_API_KEY is not configured")

    text, body = _contact_email(msg)
    await _send(
        {
            "from": _sender(msg.name),
            "to": [to],
            "reply_to": msg.email,
            "subject": f"{msg.category} enquiry from {msg.name}",
            "text": text,
            "html": body,
        }
    )


async def _send(payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise EmailError("could not reach Resend") from exc
    if res.status_code >= 300:
        log.error("Resend rejected the email: %s %s", res.status_code, res.text[:300])
        raise EmailError(f"Resend responded {res.status_code}")
