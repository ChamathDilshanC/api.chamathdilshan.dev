"""Shared schema building blocks.

Every schema here doubles as the admin form definition: the admin UI renders
forms straight from these models' JSON Schema. `widget` hints in
`json_schema_extra` pick a richer input than the plain type would (an image
picker for an image URL, a textarea for long copy, and so on).
"""

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# --- widget hints -----------------------------------------------------------


def widget(name: str, **extra: Any) -> dict[str, Any]:
    return {"widget": name, **extra}


# --- validators --------------------------------------------------------------

_SAFE_HREF_PREFIXES = ("/", "#", "https://", "http://", "mailto:", "tel:")


def _check_media_url(value: str) -> str:
    """Media must be a site-relative path or an https URL. Never javascript:/data:."""
    if value.startswith("//") or not (value.startswith("/") or value.startswith("https://")):
        raise ValueError("must be an https:// URL or a path starting with /")
    if any(c in value for c in "\"'<>\\ \n\r\t"):
        raise ValueError("contains characters that are not allowed in a URL")
    return value


def _check_href(value: str) -> str:
    if value.startswith("//") or not value.startswith(_SAFE_HREF_PREFIXES):
        raise ValueError("must start with /, #, https://, http://, mailto: or tel:")
    if any(c in value for c in "\"'<>\\\n\r\t"):
        raise ValueError("contains characters that are not allowed in a link")
    return value


def _check_external_url(value: str) -> str:
    if not value.startswith(("https://", "http://")):
        raise ValueError("must be a full URL starting with https://")
    return _check_href(value)


MediaUrl = Annotated[str, Field(max_length=1000), AfterValidator(_check_media_url)]
ImageUrl = Annotated[MediaUrl, Field(json_schema_extra=widget("image"))]
# A brand logo picked from theSVG by name in the admin
# (https://thesvg.org/icons/{slug}/{variant}.svg); any other image URL works too.
BrandIconUrl = Annotated[MediaUrl, Field(json_schema_extra=widget("brand-icon"))]
Href = Annotated[str, Field(max_length=500), AfterValidator(_check_href)]
ExternalUrl = Annotated[str, Field(max_length=500), AfterValidator(_check_external_url)]

Short = Annotated[str, Field(max_length=120)]
Line = Annotated[str, Field(max_length=300)]
Copy = Annotated[str, Field(max_length=2000, json_schema_extra=widget("textarea"))]
LongCopy = Annotated[str, Field(max_length=10_000, json_schema_extra=widget("textarea"))]
Slug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Lowercase words joined by hyphens, used in the URL.",
    ),
]


# --- base model ---------------------------------------------------------------


class CamelModel(BaseModel):
    """camelCase on the wire (matching the frontend), snake_case in Python."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ImageRef(CamelModel):
    """An image with its alt text."""

    model_config = ConfigDict(json_schema_extra=widget("image-ref"))

    url: MediaUrl
    alt: Line = ""


class MediaItem(CamelModel):
    """An image or a video. Videos play muted and looped, with an optional poster."""

    model_config = ConfigDict(json_schema_extra=widget("media"))

    kind: Literal["image", "video"] = "image"
    url: MediaUrl
    alt: Line = ""
    poster: MediaUrl | None = None


class Cta(CamelModel):
    """A labelled link."""

    label: Short
    href: Href


class Stat(CamelModel):
    label: Short
    value: Short
