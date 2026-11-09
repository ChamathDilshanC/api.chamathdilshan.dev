"""Convert HTML to journal data. Never execute, render or fetch imported markup."""

from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from typing import Annotated, Any

from pydantic import Field, ValidationError

from app.schemas.common import CamelModel
from app.schemas.entities import PostIn

MAX_HTML_BYTES = 1_048_576


class ArticleImportIn(CamelModel):
    html: Annotated[str, Field(min_length=1, max_length=MAX_HTML_BYTES)]


class ArticleImportOut(CamelModel):
    article: PostIn
    warnings: list[str]


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)


VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
IGNORED = {"script", "style", "noscript", "template", "iframe", "object", "svg"}
INLINE = {"a", "strong", "b", "em", "i", "u", "s", "small", "span", "code", "sub", "sup", "br"}
WRAPPERS = {"html", "body", "main", "article", "section", "div", "header", "figure"}


class Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1
        if self.count > 10_000 or len(self.stack) > 64:
            raise ValueError("HTML is too complex. Use the sample article structure.")
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def text(node: Node) -> str:
    def parts(item: Node | str) -> str:
        if isinstance(item, str):
            return item
        if item.tag in IGNORED:
            return ""
        if item.tag == "br":
            return "\n"
        return "".join(parts(child) for child in item.children)

    return " ".join(parts(node).split())


def import_article(html: str) -> ArticleImportOut:
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("Choose an HTML file smaller than 1 MB.")
    parser = Parser()
    parser.feed(html)
    parser.close()
    warnings: list[str] = []
    meta: dict[str, str] = {}
    headings: list[str] = []
    sections: list[dict[str, Any]] = []
    cover: dict[str, Any] | None = None

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    def section() -> dict[str, Any]:
        if not sections:
            sections.append({"title": "Introduction", "paragraphs": [], "images": [], "videos": []})
        return sections[-1]

    def media(node: Node) -> dict[str, Any]:
        src = node.attrs.get("src", "")
        if node.tag == "video" and not src:
            src = next(
                (
                    c.attrs.get("src", "")
                    for c in node.children
                    if isinstance(c, Node) and c.tag == "source"
                ),
                "",
            )
        if not src:
            raise ValueError(f"Every <{node.tag}> needs a src URL.")
        result: dict[str, Any] = {
            "kind": "video" if node.tag == "video" else "image",
            "url": src,
            "alt": node.attrs.get("alt", node.attrs.get("aria-label", "")),
        }
        if node.tag == "video":
            result["poster"] = node.attrs.get("poster") or None
        return result

    def check_inline(node: Node) -> None:
        for child in node.children:
            if isinstance(child, Node):
                if child.tag not in INLINE:
                    raise ValueError(f"Put media and other blocks outside <{node.tag}> tags.")
                check_inline(child)

    def walk(node: Node) -> None:
        nonlocal cover
        tag = node.tag
        if tag in IGNORED:
            warn(
                "Scripts, styles and embedded documents were removed. "
                "The journal keeps its own font and layout."
            )
            return
        if (
            "style" in node.attrs
            or "class" in node.attrs
            or any(k.startswith("on") for k in node.attrs)
        ):
            warn(
                "HTML styling and event handlers were removed. "
                "The journal keeps its own font and layout."
            )
        if tag == "meta":
            meta[node.attrs.get("name", "").lower()] = node.attrs.get("content", "")
        elif tag == "h1":
            check_inline(node)
            headings.append(text(node))
        elif tag in {"h2", "h3", "h4", "h5", "h6"}:
            check_inline(node)
            if not text(node):
                raise ValueError("Section headings cannot be empty.")
            sections.append({"title": text(node), "paragraphs": [], "images": [], "videos": []})
            if tag != "h2":
                warn("All section headings use the journal's existing heading style.")
        elif tag in {"p", "blockquote", "li", "pre", "figcaption"}:
            check_inline(node)
            value = text(node)
            if value:
                current = section()
                if current["images"] or current["videos"]:
                    raise ValueError(
                        "Put paragraphs before images and videos in each section, "
                        "or start a new section."
                    )
                current["paragraphs"].append(value)
            if tag != "p" or any(isinstance(c, Node) for c in node.children):
                warn(
                    "Inline formatting, links, captions and lists "
                    "are imported as plain paragraph text."
                )
        elif tag in {"img", "video"}:
            item = media(node)
            if "data-cover" in node.attrs:
                if cover is not None:
                    raise ValueError("Mark only one image or video with data-cover.")
                cover = item
            elif tag == "img":
                current = section()
                if current["videos"]:
                    raise ValueError(
                        "Put images before videos in each section, or start a new section."
                    )
                current["images"].append({"url": item["url"], "alt": item["alt"]})
            else:
                section()["videos"].append(item)
        elif tag in WRAPPERS | {"root", "head", "ul", "ol"}:
            for child in node.children:
                if isinstance(child, Node):
                    walk(child)
                elif child.strip():
                    raise ValueError(
                        "Wrap article text in <p> tags and headings in <h1>/<h2> tags."
                    )
        elif tag in {"title", "link", "base", "hr"}:
            return
        else:
            raise ValueError(f"Unsupported <{tag}> tag. Use the sample HTML format.")

    walk(parser.root)
    if len(headings) != 1 or not headings[0]:
        raise ValueError("Include exactly one non-empty <h1> article title.")
    if not sections or not any(s["paragraphs"] or s["images"] or s["videos"] for s in sections):
        raise ValueError("Include article content using <section>, <h2> and <p> tags.")
    if not cover:
        warn("No cover was marked. Add a cover in the editor before publishing.")
    if "article-date" not in meta:
        warn("No article-date was supplied; today's date was used.")
    try:
        article = PostIn.model_validate(
            {
                "title": headings[0],
                "slug": meta.get("article-slug") or None,
                "category": meta.get("article-category", ""),
                "date": meta.get("article-date", date.today().isoformat()),
                "excerpt": meta.get("description", ""),
                "cover": cover,
                "sections": sections,
                "published": False,
            }
        )
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ValueError("Check the HTML content: " + "; ".join(errors)) from exc
    return ArticleImportOut(article=article, warnings=warnings)
