"""The public contact form: validated, rate limited and emailed to the owner through Resend.

The visitor's browser posts here directly. Nothing is stored; the email is the record.
Replies go straight to the visitor because the message carries their address as Reply-To.
"""

import logging
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import AfterValidator, Field

from app.core.http_cache import no_store
from app.integrations.resend import ContactMessage, EmailError, send_contact_message
from app.schemas.common import CamelModel
from app.security.deps import require_trusted_origin
from app.security.rate_limit import contact_limit

log = logging.getLogger(__name__)
router = APIRouter()

# The WHATWG rule browsers use for <input type="email">, plus a dot in the domain.
_EMAIL = (
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _one_line(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("must be a single line of text")
    return value


Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_one_line)]


class ContactIn(CamelModel):
    first_name: Name
    last_name: Name
    email: Annotated[str, Field(max_length=200, pattern=_EMAIL)]
    category: Annotated[str, Field(min_length=1, max_length=120), AfterValidator(_one_line)]
    message: Annotated[str, Field(max_length=5000)] = ""
    # Honeypot: hidden from people, so only bots fill it in.
    website: Annotated[str, Field(max_length=500)] = ""


@router.post(
    "/contact", dependencies=[Depends(require_trusted_origin), Depends(contact_limit)]
)
async def contact(body: ContactIn, response: Response) -> dict[str, bool]:
    no_store(response)
    if body.website:
        log.info("contact form honeypot filled in — message dropped")
        return {"ok": True}
    try:
        await send_contact_message(
            ContactMessage(
                first_name=body.first_name,
                last_name=body.last_name,
                email=body.email,
                category=body.category,
                message=body.message,
            )
        )
    except EmailError as exc:
        log.error("could not send contact message: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Your message could not be sent. Try again shortly.",
        ) from exc
    return {"ok": True}
