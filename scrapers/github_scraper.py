"""GitHub profile summary using the official, public REST API (no API key needed).

Unauthenticated requests are limited to 60 per hour, which is plenty here.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Optional

from tqdm import tqdm

from scrapers.base_scraper import BaseScraper, Record

API_ROOT = "https://api.github.com"


class GitHubScraper(BaseScraper):
    """Fetch a user's profile + repositories and compute simple statistics."""

    name = "github"

    def __init__(self, username: str, **kwargs) -> None:
        # robots.txt governs HTML crawling; the official API is governed by GitHub's
        # API terms and rate limits instead, so we do not apply robots.txt here.
        kwargs.setdefault("respect_robots", False)
        super().__init__(**kwargs)
        self.username = username.strip()
        self.start_url = f"{API_ROOT}/users/{self.username}"
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    # ------------------------------------------------------------------ parsing
    def parse_page(self, html: str, page_url: str = "") -> list[Record]:
        """Parse one page of the ``/repos`` JSON response (``html`` is JSON text here)."""
        try:
            data = json.loads(html)
        except (TypeError, ValueError):
            self.logger.error("Invalid JSON for repos page %s", page_url)
            return []
        if not isinstance(data, list):
            return []
        return [
            {
                "name": repo.get("name", ""),
                "stars": int(repo.get("stargazers_count") or 0),
                "forks": int(repo.get("forks_count") or 0),
                "language": repo.get("language") or "",
                "is_fork": bool(repo.get("fork", False)),
                "url": repo.get("html_url", ""),
            }
            for repo in data
            if isinstance(repo, dict)
        ]

    @staticmethod
    def build_summary(profile: dict[str, Any], repos: list[Record], top_n: int = 5) -> Record:
        """Combine profile JSON and repo records into one flat summary record."""
        languages = Counter(r["language"] for r in repos if r["language"] and not r["is_fork"])
        top = languages.most_common(top_n)
        return {
            "name": profile.get("name") or profile.get("login", ""),
            "username": profile.get("login", ""),
            "bio": profile.get("bio") or "",
            "followers": int(profile.get("followers") or 0),
            "following": int(profile.get("following") or 0),
            "public_repos": int(profile.get("public_repos") or 0),
            "total_stars": sum(r["stars"] for r in repos),
            "top_languages": ", ".join(f"{lang} ({n})" for lang, n in top) or "n/a",
            "profile_url": profile.get("html_url", ""),
        }

    # ------------------------------------------------------------------ pipeline
    def scrape(
        self,
        max_pages: Optional[int] = 5,
        limit: Optional[int] = None,
        show_progress: bool = True,
    ) -> list[Record]:
        """Return a one-element list holding the profile summary.

        Args:
            max_pages: Pages of 100 repos to read (default 5 = up to 500 repos).
        """
        profile = self.fetch_json(self.start_url)
        if not isinstance(profile, dict):
            if self.last_error and "404" in self.last_error:
                self.last_error = f"GitHub user '{self.username}' was not found"
            return []

        repos: list[Record] = []
        pages = max_pages or 5
        for page in tqdm(range(1, pages + 1), desc="Reading repos", unit="page",
                         disable=not show_progress, leave=False):
            text = self.fetch_page(
                f"{self.start_url}/repos",
                params={"per_page": 100, "page": page, "type": "owner"},
            )
            if text is None:
                break
            batch = self.parse_page(text, f"{self.start_url}/repos?page={page}")
            repos.extend(batch)
            if len(batch) < 100:  # last page reached
                break

        return [self.build_summary(profile, repos)]
