"""HTML imports are validated draft data, never executable HTML or automatic writes."""

import pytest
from fastapi.testclient import TestClient

from app.services.article_import import import_article

HTML = """<!doctype html><html><head>
<meta name="article-category" content="Engineering">
<meta name="article-date" content="2026-11-09">
<meta name="article-slug" content="imported-article">
<meta name="description" content="A short summary.">
</head><body><article>
<h1>Imported &amp; reviewed</h1>
<img data-cover src="https://cdn.example.com/cover.jpg" alt="Cover">
<section><h2>First section</h2><p>Hello <strong>world</strong> &amp; friends.</p>
<img src="/images/one.jpg" alt="One"><img src="/images/two.jpg" alt="Two">
<video poster="/images/poster.jpg" aria-label="Demo"><source src="https://cdn.example.com/demo.mp4"></video>
</section><section><h2>Next section</h2><p>More content.</p></section>
</article></body></html>"""


def test_import_preserves_content_and_media() -> None:
    result = import_article(HTML)
    article = result.article
    assert article.title == "Imported & reviewed"
    assert article.slug == "imported-article"
    assert article.category == "Engineering"
    assert article.excerpt == "A short summary."
    assert article.date.isoformat() == "2026-11-09"
    assert article.published is False
    assert article.cover is not None and article.cover.alt == "Cover"
    section = article.sections[0]
    assert section.paragraphs == ["Hello world & friends."]
    assert [i.alt for i in section.images] == ["One", "Two"]
    assert section.videos[0].kind == "video"
    assert section.videos[0].poster == "/images/poster.jpg"
    assert section.videos[0].alt == "Demo"
    assert len(article.sections) == 2
    assert result.warnings  # Inline formatting becomes plain text.


def test_import_removes_scripts_styles_and_handlers() -> None:
    result = import_article(
        HTML.replace(
            "<article>",
            '<article class="custom" style="font-family:evil" onclick="evil()">'
            '<script>evil()</script><style>p{color:red}</style>',
        )
    )
    serialized = result.article.model_dump_json()
    assert "evil" not in serialized
    assert any("removed" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    "fragment",
    [
        '<img src="javascript:alert(1)">',
        '<img src="data:image/png;base64,abc">',
        '<img src="//evil.test/a.jpg">',
        '<img src="local.jpg">',
        '<video src="https://cdn.example.com/v.mp4" poster="javascript:x"></video>',
        "<img>",
        "<table><tr><td>Unsupported content</td></tr></table>",
        '<img src="/a.jpg"><p>Out of order</p>',
        '<img src="/a.jpg"><img src="/b.jpg"><img src="/c.jpg">',
        "<p>" + "x" * 5001 + "</p>",
    ],
)
def test_import_rejects_invalid_content(fragment: str) -> None:
    with pytest.raises(ValueError):
        import_article(f"<h1>Title</h1><section><h2>Heading</h2>{fragment}</section>")


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<p>No title</p>",
        "<h1>A</h1><h1>B</h1><p>Text</p>",
        "<h1>Title</h1>",
        "<div>" * 66,
        "x" * 1_048_577,
    ],
    ids=["empty", "missing-title", "two-titles", "missing-body", "too-deep", "too-large"],
)
def test_import_rejects_missing_structure_and_limits(html: str) -> None:
    with pytest.raises(ValueError):
        import_article(html)


def test_import_draft_defaults_and_legacy_sections() -> None:
    from app.schemas.entities import PostSectionPublic

    result = import_article("<h1>Title</h1><p>Introduction</p>")
    assert result.article.sections[0].title == "Introduction"
    assert result.article.cover is None
    assert len(result.warnings) == 2
    legacy = PostSectionPublic.model_validate({"title": "Existing", "paragraphs": [], "images": []})
    assert legacy.videos == []


def test_preview_requires_admin_and_trusted_origin(
    client: TestClient, signed_in: TestClient
) -> None:
    # The fixtures may share a client, so explicitly remove its session first.
    cookies = dict(signed_in.cookies)
    signed_in.cookies.clear()
    assert client.post("/api/admin/posts/import-preview", json={"html": HTML}).status_code == 401
    signed_in.cookies.update(cookies)
    assert (
        signed_in.post(
            "/api/admin/posts/import-preview",
            json={"html": HTML},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )


def test_preview_then_create_publish_and_read_video(signed_in: TestClient) -> None:
    preview = signed_in.post("/api/admin/posts/import-preview", json={"html": HTML})
    assert preview.status_code == 200, preview.text
    assert "no-store" in preview.headers["cache-control"]
    assert signed_in.get("/api/admin/posts").json() == []
    article = preview.json()["article"]
    created = signed_in.post("/api/admin/posts", json=article)
    assert created.status_code == 201, created.text
    assert created.json()["published"] is False
    assert signed_in.get("/api/posts/imported-article").status_code == 404
    published = signed_in.put(
        f"/api/admin/posts/{created.json()['id']}", json={**article, "published": True}
    )
    assert published.status_code == 200, published.text
    public = signed_in.get("/api/posts/imported-article")
    assert public.status_code == 200, public.text
    assert public.json()["sections"][0]["videos"][0]["url"] == "https://cdn.example.com/demo.mp4"


def test_preview_validation_errors_are_actionable(signed_in: TestClient) -> None:
    res = signed_in.post("/api/admin/posts/import-preview", json={"html": "<p>Missing title</p>"})
    assert res.status_code == 422
    assert "h1" in res.json()["detail"]
    res = signed_in.post("/api/admin/posts/import-preview", json={"html": "x" * 1_048_577})
    assert res.status_code == 422
