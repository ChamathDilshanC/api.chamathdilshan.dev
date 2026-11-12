"""Pure safety and schema checks for GitHub AI Project Studio."""

from app.integrations.github import GitHubError, normalize_repository_url, redact_content
from app.schemas.studio import StudioContent


def test_github_urls_are_normalized_without_accepting_other_hosts() -> None:
    repository = normalize_repository_url("https://github.com/ChamathDilshanC/demo.git/issues")
    assert repository.owner == "ChamathDilshanC"
    assert repository.name == "demo"
    assert repository.url == "https://github.com/ChamathDilshanC/demo"

    try:
        normalize_repository_url("https://example.com/owner/demo")
    except GitHubError as exc:
        assert "GitHub" in str(exc)
    else:
        raise AssertionError("non-GitHub host was accepted")


def test_secret_files_and_values_are_redacted() -> None:
    assert redact_content(".env", "GEMINI_API_KEY=secret")[0] is None
    safe, changed = redact_content("README.md", "api_key=secret\nfeature: import")
    assert changed
    assert safe is not None
    assert "secret" not in safe
    assert "[REDACTED]" in safe


def test_studio_content_rejects_unstructured_ai_fields() -> None:
    content = StudioContent(title="Demo", summary="Verified summary")
    assert content.title == "Demo"
