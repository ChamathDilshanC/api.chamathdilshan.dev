"""Public, bounded AI chat about Chamath's portfolio and experience."""

import inspect
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import Field

from app.core.config import settings
from app.core.http_cache import no_store
from app.schemas.common import CamelModel
from app.security.deps import DB, require_trusted_origin
from app.security.rate_limit import chat_limit
from app.services import experience, posts, projects, sections, skills

router = APIRouter()


class ChatMessage(CamelModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=2000)


class ChatIn(CamelModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=8)


def _event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _context(payloads: dict[str, Any]) -> str:
    encoded = json.dumps(payloads, separators=(",", ":"), default=str)
    return encoded[:28_000]


async def _portfolio_context(db: Any) -> str:
    content = await sections.public_content(db)
    project_list = await projects.public_list(db)
    post_list = await posts.public_list(db)
    skill_list = await skills.public_list(db)
    experience_list = await experience.public_list(db)
    return _context(
        {
            "content": content,
            "projects": project_list,
            "articles": post_list,
            "skills": skill_list,
            "experience": experience_list,
        }
    )


def _prompt(body: ChatIn, context: str) -> str:
    history = "\n".join(f"{item.role}: {item.content}" for item in body.history[-8:])
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
        "max_tokens": 500,
        "stream": True,
    }
    async with httpx.AsyncClient(
        timeout=settings.AI_PROVIDER_TIMEOUT_SECONDS, headers=headers
    ) as client:
        async with client.stream(
            "POST", f"{base_url.rstrip('/')}/chat/completions", json=payload
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


async def _stream_gemini(prompt: str) -> AsyncIterator[str]:
    from google import genai  # type: ignore[import-not-found, unused-ignore]
    from google.genai import types  # type: ignore[import-not-found, unused-ignore]

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(api_version=settings.GEMINI_API_VERSION),
    )
    stream: Any = client.aio.models.generate_content_stream(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.35, max_output_tokens=500),
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
