"""Bounded, server-side GitHub API access for the Project Studio."""

import base64
import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from app.core.config import settings

SENSITIVE_NAME = re.compile(
    r"(^|/)(\.env(?:\.|$)|.*\.pem$|.*\.key$|id_rsa(?:\.|$)|credentials?\.|.*secret.*|.*token.*)$",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*[^\s,;]+"
)
HIGH_SIGNAL = re.compile(
    r"(?i)(^|/)(readme(?:\.md)?|package\.json|pnpm-lock\.yaml|yarn\.lock|package-lock\.json|"
    r"pyproject\.toml|requirements(?:\.txt)?|poetry\.lock|pom\.xml|build\.gradle|dockerfile|"
    r"docker-compose[^/]*|\.gitmodules|.*\.ya?ml|.*\.json|src/.*\.(ts|tsx|js|jsx|py|java|go|rs)|"
    r"app/.*\.(ts|tsx|js|jsx|py)|pages/.*\.(ts|tsx|js|jsx))$"
)
MEDIA = re.compile(r"(?i)\.(png|jpe?g|webp|gif|svg|mp4|webm)$")


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retry_after: str | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str
    url: str


def normalize_repository_url(value: str) -> GitHubRepository:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        raise GitHubError(
            "Use a public GitHub repository URL such as https://github.com/owner/name."
        )
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts[:2]):
        raise GitHubError("That GitHub URL does not contain a valid owner and repository name.")
    owner, name = parts[:2]
    name = name.removesuffix(".git")
    return GitHubRepository(owner, name, f"https://github.com/{owner}/{name}")


def redact_content(path: str, content: str) -> tuple[str | None, bool]:
    if SENSITIVE_NAME.search(path):
        return None, True
    redacted = SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", content)
    return redacted, redacted != content


class GitHubClient:
    def __init__(self) -> None:
        self.base = settings.GITHUB_API_URL.rstrip("/")
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "chamathdilshan-project-studio",
        }
        if settings.GITHUB_TOKEN:
            self.headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with httpx.AsyncClient(
                timeout=settings.GITHUB_TIMEOUT_SECONDS, headers=self.headers
            ) as client:
                response = await client.get(f"{self.base}{path}", params=params)
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub took too long to respond. Try again shortly.") from exc
        except httpx.HTTPError as exc:
            raise GitHubError("GitHub is temporarily unavailable.") from exc
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError(
                "GitHub API rate limit reached. Try again later.",
                429,
                response.headers.get("retry-after"),
            )
        if response.status_code == 429:
            raise GitHubError(
                "GitHub asked us to slow down. Try again later.",
                429,
                response.headers.get("retry-after"),
            )
        if response.status_code == 404:
            raise GitHubError(
                "Repository not found or not accessible with the configured GitHub connection.", 404
            )
        if response.status_code >= 400:
            raise GitHubError(
                "GitHub rejected the request. Check the connection permissions.",
                response.status_code,
            )
        return response.json()

    async def list_repositories(
        self,
        page: int,
        per_page: int,
        search: str,
        sort: str,
        visibility: str,
        include_forks: bool = True,
        include_archived: bool = True,
    ) -> tuple[list[dict[str, Any]], int | None]:
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "sort": sort
            if sort in {"created", "updated", "pushed", "full_name", "stars"}
            else "updated",
            "direction": "desc",
        }
        if search:
            data = await self._request(
                "/search/repositories",
                {
                    "q": f"{search} user:{settings.GITHUB_ACCOUNT}",
                    "page": page,
                    "per_page": per_page,
                    "sort": "updated",
                },
            )
            items = data.get("items", [])
        else:
            items = await self._request(f"/users/{settings.GITHUB_ACCOUNT}/repos", params)
        filtered = [
            item
            for item in items
            if visibility == "all"
            or (visibility == "private" and item.get("private"))
            or (visibility == "public" and not item.get("private"))
        ]
        filtered = [
            item
            for item in filtered
            if (include_forks or not item.get("fork"))
            and (include_archived or not item.get("archived"))
        ]
        return filtered, int(data.get("total_count", len(items))) if search else None

    async def repository(self, repository: GitHubRepository) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._request(f"/repos/{repository.owner}/{repository.name}"),
        )

    async def tree(self, repository: GitHubRepository, ref: str) -> list[dict[str, Any]]:
        data = await self._request(
            f"/repos/{repository.owner}/{repository.name}/git/trees/{ref}", {"recursive": "1"}
        )
        return cast(list[dict[str, Any]], data.get("tree", []))

    async def latest_commit(self, repository: GitHubRepository, ref: str) -> str:
        data = await self._request(f"/repos/{repository.owner}/{repository.name}/commits/{ref}")
        return str(data.get("sha", "unknown"))

    async def file(self, repository: GitHubRepository, path: str, ref: str) -> str | None:
        data = await self._request(
            f"/repos/{repository.owner}/{repository.name}/contents/{path}", {"ref": ref}
        )
        if data.get("type") != "file" or data.get("size", 0) > settings.GITHUB_MAX_BYTES:
            return None
        try:
            return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None
