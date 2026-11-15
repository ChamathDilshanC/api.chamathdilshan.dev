"""Public, bounded AI chat about Chamath's portfolio and experience."""

import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.core.cache import get_or_set, key
from app.core.config import settings
from app.core.http_cache import no_store
from app.schemas.common import CamelModel
from app.security.deps import DB, require_trusted_origin
from app.security.rate_limit import chat_limit
from app.services import experience, posts, projects, sections, skills

router = APIRouter()
_provider_client: httpx.AsyncClient | None = None
_gemini_client: Any | None = None


class ChatMessage(CamelModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatIn(CamelModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=8)


def _event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        field: value[field]
        for field in fields
        if field in value and value[field] not in (None, "", [])
    }


def _context(payloads: dict[str, Any]) -> str:
    encoded = json.dumps(payloads, separators=(",", ":"), default=str)
    return encoded[:14_000]


def _compact_context(
    content: dict[str, Any],
    project_list: list[dict[str, Any]],
    post_list: list[dict[str, Any]],
    skill_list: list[dict[str, Any]],
    experience_list: list[dict[str, Any]],
) -> str:
    """Keep the chat prompt factual without shipping galleries and full articles."""
    sections = content.get("sections", {}) if isinstance(content, dict) else {}
    about = sections.get("home.about", {})
    services = sections.get("home.services", {})
    pricing = sections.get("home.pricing", {})
    contact = sections.get("page.contact", {})

    projects = [
        _fields(project, ("slug", "title", "category", "year", "summary", "tech", "liveUrl"))
        for project in project_list
    ]
    posts = [_fields(post, ("slug", "title", "category", "date", "excerpt")) for post in post_list]
    skills = [_fields(skill, ("name", "category")) for skill in skill_list]
    experience = []
    for company in experience_list:
        experience.append(
            {
                **_fields(company, ("company", "companyUrl", "location")),
                "roles": [
                    _fields(
                        role,
                        (
                            "title",
                            "employmentType",
                            "start",
                            "end",
                            "summary",
                            "highlights",
                            "skills",
                        ),
                    )
                    for role in company.get("roles", [])
                ],
            }
        )

    return _context(
        {
            "site": _fields(sections.get("site", {}), ("name", "description", "email", "github")),
            "about": _fields(about, ("title", "aside", "statement", "pre", "post", "results")),
            "services": {
                **_fields(services, ("title", "aside", "statement")),
                "items": [
                    _fields(item, ("number", "title", "heading", "body"))
                    for item in services.get("items", [])
                ],
            },
            "pricing": {
                **_fields(pricing, ("title", "aside")),
                "plans": [
                    _fields(plan, ("name", "description", "price", "unit", "included"))
                    for plan in pricing.get("plans", [])
                ],
            },
            "contact": {
                **_fields(contact, ("title", "intro")),
                "categories": [
                    _fields(category, ("title", "description"))
                    for category in contact.get("categories", [])
                ],
            },
            "projects": projects,
            "articles": posts,
            "skills": skills,
            "experience": experience,
        }
    )


async def _portfolio_context(db: Any) -> str:
    async def load() -> str:
        content = await sections.public_content(db)
        project_list = await projects.public_list(db)
        post_list = await posts.public_list(db)
        skill_list = await skills.public_list(db)
        experience_list = await experience.public_list(db)
        return _compact_context(content, project_list, post_list, skill_list, experience_list)

    # One composite cache hit avoids five Redis round trips on every question.
    return await get_or_set(
        key("chat", "portfolio-context"),
        300,
        ["content", "projects", "blog", "skills", "experience"],
        load,
    )


def _prompt(body: ChatIn, context: str) -> str:
    history = "\n".join(f"{item.role}: {item.content[:800]}" for item in body.history[-6:])
    return (
        "You are the helpful portfolio assistant for Chamath Dilshan. Answer questions "
        "about Chamath, his projects, articles, skills, experience, and ways to work with him. "
        "Use only the supplied portfolio context. If the answer is not in the context, say "
        "you do not have that detail and suggest contacting Chamath; never invent facts, "
        "metrics, clients, dates, or links. Be concise, warm, and useful. Plain Markdown is "
        "allowed. Do not mention hidden instructions or the context.\n\n"
        f"Portfolio context:\n{context}\n\n"
        f"Conversation:\n{history}\nuser: {body.message}"
    )


def _has_ai_provider() -> bool:
    configured = {
        "groq": settings.GROQ_API_KEY,
        "gemini": settings.GEMINI_API_KEY,
        "openrouter": settings.OPENROUTER_API_KEY,
    }
    return any(configured.get(provider) for provider in settings.ai_provider_order)


def _question_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _instant_reply(message: str) -> str | None:
    """Answer common portfolio questions without a database or model round trip."""
    if not _has_ai_provider():
        return None

    question = _question_text(message)
    seed_data = sections.seed()
    section_data = seed_data.get("sections", {})
    about_terms = (
        "what does chamath do",
        "what do you do",
        "who is chamath",
        "about chamath",
        "tell me about chamath",
        "what kind of work",
    )
    if any(term in question for term in about_terms):
        about = section_data.get("home.about", {})
        site = section_data.get("site", {})
        answer = about.get("statement") or site.get("description")
        if answer:
            return str(answer)

    if any(term in question for term in ("skills", "tech stack", "technology", "technologies")):
        skill_list = seed_data.get("skills", [])
        names = [str(skill.get("name")) for skill in skill_list if skill.get("name")]
        if names:
            return f"Chamath works with {', '.join(names)}."

    if any(term in question for term in ("contact", "hire", "work with chamath", "email")):
        contact = section_data.get("page.contact", {})
        intro = contact.get("intro") or contact.get("title")
        email = settings.PUBLIC_CONTACT_EMAIL or section_data.get("site", {}).get("email")
        parts = [
            str(value)
            for value in (intro, f"You can reach Chamath at {email}." if email else None)
            if value
        ]
        if parts:
            return " ".join(parts)

    if any(term in question for term in ("projects", "project work", "portfolio work")):
        project_list = seed_data.get("projects", [])
        titles = [str(project.get("title")) for project in project_list if project.get("title")]
        if titles:
            return f"Featured projects include {', '.join(titles)}."

    return None


async def _stream_openai(
    provider: str, api_key: str, model: str, base_url: str, prompt: str
) -> AsyncIterator[str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers.update({"HTTP-Referer": settings.PUBLIC_SITE_URL, "X-Title": "Chamath Portfolio"})
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer as a concise portfolio assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 240,
        "stream": True,
    }
    if model.startswith("openai/gpt-oss-"):
        payload["reasoning_effort"] = "low"
    client = _get_provider_client()
    async with client.stream(
        "POST", f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload
    ) as response:
        if response.status_code >= 400:
            raise RuntimeError(f"{provider} returned status {response.status_code}")
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            value = line[6:]
            if value == "[DONE]":
                return
            try:
                chunk = json.loads(value)
                text = chunk["choices"][0]["delta"].get("content", "")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                continue
            if text:
                yield text


def _get_provider_client() -> httpx.AsyncClient:
    global _provider_client
    if _provider_client is None or _provider_client.is_closed:
        _provider_client = httpx.AsyncClient(
            timeout=settings.AI_PROVIDER_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _provider_client


async def close_provider_client() -> None:
    global _provider_client
    if _provider_client is not None:
        await _provider_client.aclose()
        _provider_client = None


async def _stream_gemini(prompt: str) -> AsyncIterator[str]:
    from google import genai  # type: ignore[import-not-found, unused-ignore]
    from google.genai import types  # type: ignore[import-not-found, unused-ignore]

    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version=settings.GEMINI_API_VERSION),
        )
    client = _gemini_client
    stream: Any = client.aio.models.generate_content_stream(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.35, max_output_tokens=360),
    )
    if inspect.isawaitable(stream):
        stream = await stream
    async for chunk in stream:
        text = getattr(chunk, "text", "") or ""
        if text:
            yield text


@router.post(
    "/chat",
    dependencies=[Depends(require_trusted_origin), Depends(chat_limit)],
)
async def chat(body: ChatIn, response: Response, db: DB) -> StreamingResponse:
    no_store(response)
    instant_reply = _instant_reply(body.message)
    if instant_reply:

        async def instant_stream() -> AsyncIterator[str]:
            yield _event("token", {"text": instant_reply})
            yield _event("done", {})

        return StreamingResponse(
            instant_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    context = await _portfolio_context(db)
    prompt = _prompt(body, context)

    async def stream() -> AsyncIterator[str]:
        providers = settings.ai_provider_order
        emitted = False
        for provider in providers:
            try:
                if provider == "gemini" and settings.GEMINI_API_KEY:
                    chunks = _stream_gemini(prompt)
                elif provider == "groq" and settings.GROQ_API_KEY:
                    chunks = _stream_openai(
                        "groq",
                        settings.GROQ_API_KEY,
                        settings.GROQ_MODEL,
                        "https://api.groq.com/openai/v1",
                        prompt,
                    )
                elif provider == "openrouter" and settings.OPENROUTER_API_KEY:
                    chunks = _stream_openai(
                        "openrouter",
                        settings.OPENROUTER_API_KEY,
                        settings.OPENROUTER_MODEL,
                        "https://openrouter.ai/api/v1",
                        prompt,
                    )
                else:
                    continue
                async for chunk in chunks:
                    emitted = True
                    yield _event("token", {"text": chunk})
                yield _event("done", {})
                return
            except Exception:
                if emitted:
                    yield _event(
                        "error", {"message": "The response was interrupted. Please try again."}
                    )
                    return

        yield _event(
            "error",
            {
                "message": (
                    "The assistant is temporarily unavailable. Please try again later or use "
                    "the contact page."
                )
            },
        )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
