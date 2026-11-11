"""Protected work-experience document uploads and delivery."""

import secrets
import time
from pathlib import PurePath

import cloudinary
from cloudinary.utils import private_download_url

from app.core.config import settings
from app.integrations import cloudinary as cloudinary_api
from app.integrations.cloudinary import CloudinaryError
from app.schemas.entities import (
    ExperienceDocumentIn,
    ExperienceDocumentRegister,
    ExperienceDocumentSignature,
)

MAX_DOCUMENT_BYTES = 15 * 1024 * 1024


def _require_configured() -> None:
    if not settings.cloudinary_configured:
        raise CloudinaryError("Cloudinary is not configured.")


def signature(subfolder: str | None = None) -> ExperienceDocumentSignature:
    """Sign an authenticated browser upload into the experience folder."""
    _require_configured()
    suffix = "experience" if not subfolder else f"experience/{subfolder}"
    return ExperienceDocumentSignature.model_validate(
        cloudinary_api.upload_signature(suffix, delivery_type="authenticated")
    )


def register(data: ExperienceDocumentRegister) -> ExperienceDocumentIn:
    """Validate Cloudinary's signed response and return a storable reference."""
    _require_configured()
    if data.resource_type != "image" or data.format != "png":
        raise CloudinaryError("Only PNG documents are supported.")
    if not cloudinary_api.verify_upload_response(data.public_id, data.version, data.signature):
        raise CloudinaryError("Cloudinary upload signature is invalid.")

    folder = settings.CLOUDINARY_FOLDER.strip("/")
    if not data.public_id.startswith(f"{folder}/experience/"):
        raise CloudinaryError("Document was uploaded outside the experience folder.")
    expected_url = (
        f"{cloudinary_api.delivery_prefix()}{data.resource_type}/authenticated/"
    )
    if not data.secure_url.startswith(expected_url):
        raise CloudinaryError("Document URL is not an authenticated Cloudinary asset.")
    if data.bytes > MAX_DOCUMENT_BYTES:
        raise CloudinaryError("Document is larger than 15 MB.")

    filename = PurePath(data.original_filename).name[:300]
    label = PurePath(filename).stem.replace("_", " ").replace("-", " ").strip()
    return ExperienceDocumentIn(
        id=secrets.token_urlsafe(12),
        label=label[:80] or "Document",
        public_id=data.public_id,
        version=data.version,
        resource_type=data.resource_type,
        format=data.format,
        pages=data.pages,
        bytes=data.bytes,
        original_filename=filename,
    )


def delivery_url(document: ExperienceDocumentIn) -> str:
    """Create a short-lived CDN URL for a validated protected document."""
    _require_configured()
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        signature_algorithm=settings.CLOUDINARY_SIGNATURE_ALGORITHM,
        secure=True,
    )
    url = private_download_url(
        document.public_id,
        document.format,
        resource_type=document.resource_type,
        type="authenticated",
        expires_at=int(time.time()) + 30,
        attachment=False,
        transformation={"width": 1800, "height": 2400, "crop": "limit"},
    )
    return str(url)
