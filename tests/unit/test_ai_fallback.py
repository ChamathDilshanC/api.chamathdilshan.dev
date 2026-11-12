"""Deterministic routing tests for the multi-provider generation boundary."""

import pytest

from app.core.config import settings
from app.integrations import ai_fallback
from app.integrations.ai_fallback import AIGeneration, AIProviderError
from app.schemas.studio import GeminiDraft, RepositoryAnalysis, RepositorySummary


def _analysis() -> RepositoryAnalysis:
    return RepositoryAnalysis(
        repository=RepositorySummary(
            owner="owner",
            name="demo",
            full_name="owner/demo",
            html_url="https://github.com/owner/demo",
        ),
        source_sha="abc123",
        files_scanned=["README.md"],
    )


class _Unavailable:
    name = "gemini"
    model = "gemini-test"

    async def generate(self, _: RepositoryAnalysis) -> tuple[GeminiDraft, None]:
        raise AIProviderError(
            "temporarily unavailable", 503, code="gemini_unavailable", retryable=True
        )


class _Success:
    name = "groq"
    model = "groq-test"

    async def generate(self, _: RepositoryAnalysis) -> tuple[GeminiDraft, None]:
        return GeminiDraft(title="Fallback draft"), None


@pytest.mark.asyncio
async def test_recoverable_primary_failure_uses_next_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AI_FALLBACK_ENABLED", True)
    monkeypatch.setattr(ai_fallback, "_configured_providers", lambda: [_Unavailable(), _Success()])

    result = await ai_fallback.generate_with_fallback(_analysis())

    assert isinstance(result, AIGeneration)
    assert result.provider == "groq"
    assert result.model == "groq-test"
    assert result.failures[0].code == "gemini_unavailable"


@pytest.mark.asyncio
async def test_nonrecoverable_failure_does_not_try_next_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InvalidCredentials(_Unavailable):
        async def generate(self, _: RepositoryAnalysis) -> tuple[GeminiDraft, None]:
            raise AIProviderError("access rejected", 502, code="gemini_authentication")

    called = False

    async def should_not_run(_: RepositoryAnalysis) -> tuple[GeminiDraft, None]:
        nonlocal called
        called = True
        return GeminiDraft(title="unexpected"), None

    class _Never:
        name = "groq"
        model = "groq-test"
        generate = should_not_run

    monkeypatch.setattr(
        ai_fallback, "_configured_providers", lambda: [_InvalidCredentials(), _Never()]
    )

    with pytest.raises(AIProviderError) as caught:
        await ai_fallback.generate_with_fallback(_analysis())

    assert caught.value.code == "gemini_authentication"
    assert not called


def test_openai_schema_is_strict_at_every_object_level() -> None:
    assert ai_fallback.OPENAI_DRAFT_SCHEMA["additionalProperties"] is False
    for value in ai_fallback.OPENAI_DRAFT_SCHEMA["properties"].values():
        if value.get("type") == "object":
            assert value["additionalProperties"] is False
            assert set(value["required"]) == set(value["properties"])
