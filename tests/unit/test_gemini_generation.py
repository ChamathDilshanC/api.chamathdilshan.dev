"""Regression tests for the Gemini generation boundary."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.core import db as db_module
from app.core.config import settings
from app.integrations import gemini
from app.integrations.gemini import GeminiGeneration, GeminiGenerationError
from app.integrations.github import GitHubError
from app.models import ProjectStudioDraft
from app.schemas.studio import GeminiDraft, GenerateDraftIn, RepositoryAnalysis, RepositorySummary
from app.services import studio


def _response(text: str = '{"title":"Demo"}', *, parsed: object = None, reason: str | None = None):
    candidate = SimpleNamespace(finish_reason=reason) if reason else None
    return SimpleNamespace(
        text=text,
        parsed=parsed,
        candidates=[candidate] if candidate else [],
        usage_metadata=SimpleNamespace(
            prompt_token_count=10,
            candidates_token_count=12,
            total_token_count=22,
        ),
    )


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


def test_response_schema_accepts_valid_json_and_records_usage() -> None:
    result = gemini._response_content(_response())
    assert result.title == "Demo"
    assert gemini._usage(_response()) == {
        "promptTokens": 10,
        "outputTokens": 12,
        "totalTokens": 22,
    }


def test_provider_schema_avoids_unsupported_dynamic_and_reference_shapes() -> None:
    schema = gemini.GEMINI_RESPONSE_SCHEMA
    assert schema["type"] == "object"
    assert "$defs" not in schema
    assert "additionalProperties" not in schema
    assert schema["properties"]["techStack"]["type"] == "array"


def test_response_uses_native_parsed_object_when_available() -> None:
    result = gemini._response_content(_response(parsed=GeminiDraft(title="Parsed")))
    assert result.title == "Parsed"


@pytest.mark.parametrize(
    "text, code",
    [
        ("", "gemini_empty_output"),
        ('{"summary":"missing title"}', "gemini_invalid_output"),
        ("not json", "gemini_invalid_output"),
        ("```json\n{\"title\":\"Repaired\"}\n```", "ok"),
    ],
)
def test_empty_invalid_missing_and_wrapped_output(text: str, code: str) -> None:
    if code == "ok":
        assert gemini._response_content(_response(text)).title == "Repaired"
        return
    with pytest.raises(GeminiGenerationError) as caught:
        gemini._response_content(_response(text))
    assert caught.value.code == code


def test_truncated_output_is_reported_without_exposing_provider_text() -> None:
    with pytest.raises(GeminiGenerationError) as caught:
        gemini._response_content(_response('{"title":"partial"}', reason="MAX_TOKENS"))
    assert caught.value.code == "gemini_incomplete_output"
    assert "partial" not in str(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403, 429, 503])
def test_provider_statuses_are_safely_classified(status: int) -> None:
    error = gemini._provider_error(SimpleNamespace(status_code=status))
    assert error.diagnostics.get("provider_status") == status
    assert "secret" not in str(error).lower()
    if status == 429:
        assert error.status == 429
        assert error.retryable
    elif status in {401, 403}:
        assert error.code == "gemini_authentication"
        assert not error.retryable
    elif status == 400:
        assert error.code == "gemini_invalid_request"
        assert not error.retryable
    else:
        assert error.code == "gemini_unavailable"
        assert error.retryable


def test_invalid_provider_request_diagnostics_are_sanitized() -> None:
    error = gemini._provider_error(
        ValueError("provider response contained a secret"), stage="configuration"
    )
    assert error.code == "gemini_invalid_request"
    assert error.diagnostics == {"stage": "configuration", "exception_type": "ValueError"}
    assert "secret" not in str(error).lower()


@pytest.mark.asyncio
async def test_timeout_retries_once_then_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeModels:
        calls = 0

        async def generate_content(self, **_: object) -> object:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return _response()

    models = FakeModels()
    captured: dict[str, object] = {}
    _install_fake_google(monkeypatch, models, captured)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "configured-for-test")
    monkeypatch.setattr(settings, "GEMINI_MAX_RETRIES", 1)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)

    result = await gemini.generate_project_draft(_analysis())
    assert result.content.title == "Demo"
    assert models.calls == 2
    assert getattr(captured["http_options"], "api_version") == "v1beta"


@pytest.mark.asyncio
async def test_timeout_exhaustion_is_504_and_does_not_leak_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeModels:
        async def generate_content(self, **_: object) -> object:
            raise TimeoutError("provider details must not escape")

    _install_fake_google(monkeypatch, FakeModels())
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "configured-for-test")
    monkeypatch.setattr(settings, "GEMINI_MAX_RETRIES", 1)
    monkeypatch.setattr(gemini.asyncio, "sleep", _no_sleep)

    with pytest.raises(GeminiGenerationError) as caught:
        await gemini.generate_project_draft(_analysis())
    assert caught.value.status == 504
    assert caught.value.code == "gemini_timeout"
    assert "provider details" not in str(caught.value)


@pytest.mark.asyncio
async def test_generation_releases_session_before_provider_and_persists_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis()
    draft_id = "a" * 16
    async with db_module.get_sessionmaker()() as db:
        db.add(
            ProjectStudioDraft(
                id=draft_id,
                repository_url=str(analysis.repository.html_url),
                source_sha=analysis.source_sha,
                status="analyzed",
                analysis=analysis.model_dump(mode="json", by_alias=True),
                evidence=[],
            )
        )
        await db.commit()

        async def fake_generate(_: RepositoryAnalysis) -> GeminiGeneration:
            return GeminiGeneration(
                content=GeminiDraft(
                    title="Generated",
                    summary="A verified project summary.",
                    headline="A generated project case study.",
                    brief={"overview": "A verified overview.", "purpose": "A verified purpose."},
                    tech_stack=[{"category": "Framework", "technologies": ["FastAPI"]}],
                    architecture=[{"title": "API", "body": "FastAPI routes are present."}],
                    case_study={
                        "problem": "A verified engineering problem.",
                        "approach": "A verified engineering approach.",
                    },
                ),
                token_usage={"totalTokens": 3},
            )

        monkeypatch.setattr(studio, "_ai_generate", fake_generate)
        result = await studio.generate(db, GenerateDraftIn(draft_id=draft_id))

        assert result.status == "review"
        assert result.token_usage == {"totalTokens": 3}
        assert result.content["title"] == "Generated"
        assert result.content["techStack"] == {"Framework": ["FastAPI"]}


@pytest.mark.asyncio
async def test_duplicate_generation_is_rejected_without_calling_provider() -> None:
    analysis = _analysis()
    draft_id = "b" * 16
    async with db_module.get_sessionmaker()() as db:
        db.add(
            ProjectStudioDraft(
                id=draft_id,
                repository_url=str(analysis.repository.html_url),
                source_sha=analysis.source_sha,
                status="generating",
                analysis=analysis.model_dump(mode="json", by_alias=True),
                evidence=[],
            )
        )
        await db.commit()

        with pytest.raises(GitHubError) as caught:
            await studio.generate(db, GenerateDraftIn(draft_id=draft_id))
        assert caught.value.code == "generation_in_progress"


async def _no_sleep(_: float) -> None:
    return None


def _install_fake_google(
    monkeypatch: pytest.MonkeyPatch,
    models: object,
    captured: dict[str, object] | None = None,
) -> None:
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    types = ModuleType("google.genai.types")

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            if captured is not None:
                captured.update(kwargs)
            self.aio = SimpleNamespace(models=models)

    class HttpOptions:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class GenerateContentConfig:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    genai.Client = FakeClient  # type: ignore[attr-defined]
    types.HttpOptions = HttpOptions  # type: ignore[attr-defined]
    types.GenerateContentConfig = GenerateContentConfig  # type: ignore[attr-defined]
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)
