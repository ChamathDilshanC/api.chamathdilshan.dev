"""Cloudinary: signed direct uploads, response verification and deletion.

Files go from the admin's browser straight to Cloudinary, so large videos never
pass through this API. This server only signs the upload, checks the signed
response before recording it, and deletes assets.
https://cloudinary.com/documentation/authentication_signatures
"""

import hashlib
import hmac
import time
from typing import Any

import httpx

from app.core.config import settings

API_BASE = "https://api.cloudinary.com/v1_1"


class CloudinaryError(Exception):
    pass


def _digest(payload: str) -> str:
    if settings.CLOUDINARY_SIGNATURE_ALGORITHM.lower() == "sha256":
        return hashlib.sha256(payload.encode()).hexdigest()
    # SHA-1 is Cloudinary's default request-signing algorithm, not our choice.
    return hashlib.sha1(payload.encode()).hexdigest()  # noqa: S324


_UNSIGNED = {"file", "api_key", "cloud_name", "resource_type"}


def sign(params: dict[str, Any]) -> str:
    """Cloudinary request signature: sorted key=value pairs joined by &, plus the secret."""
    pairs = sorted(
        (k, v) for k, v in params.items() if v not in (None, "") and k not in _UNSIGNED
    )
    to_sign = "&".join(f"{k}={v}" for k, v in pairs)
    return _digest(to_sign + settings.CLOUDINARY_API_SECRET)


def upload_signature() -> dict[str, Any]:
    timestamp = int(time.time())
    folder = settings.CLOUDINARY_FOLDER
    params = {"timestamp": timestamp, "folder": folder}
    return {
        "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
        "api_key": settings.CLOUDINARY_API_KEY,
        "timestamp": timestamp,
        "folder": folder,
        "signature": sign(params),
        "upload_url": f"{API_BASE}/{settings.CLOUDINARY_CLOUD_NAME}/auto/upload",
    }


def verify_upload_response(public_id: str, version: int, signature: str) -> bool:
    """True when the upload response was produced by Cloudinary for this account."""
    expected = sign({"public_id": public_id, "version": version})
    return hmac.compare_digest(expected, signature)


def delivery_prefix() -> str:
    return f"https://res.cloudinary.com/{settings.CLOUDINARY_CLOUD_NAME}/"


def video_poster(url: str) -> str:
    """First-frame JPEG for a Cloudinary video URL."""
    if "/video/upload/" not in url:
        return url
    head, tail = url.split("/video/upload/", 1)
    stem = tail.rsplit(".", 1)[0] if "." in tail.rsplit("/", 1)[-1] else tail
    return f"{head}/video/upload/so_0/{stem}.jpg"


async def destroy(public_id: str, resource_type: str) -> None:
    timestamp = int(time.time())
    params: dict[str, Any] = {"public_id": public_id, "timestamp": timestamp, "invalidate": "true"}
    data = {**params, "api_key": settings.CLOUDINARY_API_KEY, "signature": sign(params)}
    url = f"{API_BASE}/{settings.CLOUDINARY_CLOUD_NAME}/{resource_type}/destroy"
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            raise CloudinaryError("could not reach Cloudinary") from exc
    if res.status_code != 200:
        raise CloudinaryError(f"Cloudinary responded {res.status_code}")
    result = res.json().get("result")
    if result not in {"ok", "not found"}:
        raise CloudinaryError(f"Cloudinary could not delete the asset: {result}")
