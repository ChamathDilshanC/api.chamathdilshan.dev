"""Transactional email through Resend (https://resend.com/docs/api-reference/emails/send-email)."""

import html
import logging

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
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": settings.RESEND_FROM,
                    "to": [to],
                    "subject": f"{code} is your admin sign-in code",
                    "text": text,
                    "html": body,
                },
            )
        except httpx.HTTPError as exc:
            raise EmailError("could not reach Resend") from exc
    if res.status_code >= 300:
        log.error("Resend rejected the email: %s %s", res.status_code, res.text[:300])
        raise EmailError(f"Resend responded {res.status_code}")
