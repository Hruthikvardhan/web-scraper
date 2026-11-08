"""Scraper for the Hacker News front page (https://news.ycombinator.com)."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, Record

BASE = "https://news.ycombinator.com/"


class HackerNewsScraper(BaseScraper):
    """Extract rank, title, link, points and comment count of front-page stories.

    Note: HN's robots.txt asks for a ``Crawl-delay`` (30 s at the time of writing);
    ``BaseScraper`` honours it automatically when you request more than one page.
    """

    name = "hackernews"
    start_url = BASE
    dedupe_keys = ("title", "link")

    @staticmethod
    def _first_int(text: str, default: int = 0) -> int:
        match = re.search(r"\d+", text or "")
        return int(match.group()) if match else default

    def parse_page(self, html: str, page_url: str = "") -> list[Record]:
        """Parse one HN page. Each story is a ``tr.athing`` row followed by a subtext row."""
        soup = BeautifulSoup(html, "lxml")
        records: list[Record] = []
        for row in soup.select("tr.athing"):
            try:
                title_link = row.select_one("span.titleline > a") or row.select_one("a.titlelink")
                href = self.safe_attr(title_link, "href")
                sub = row.find_next_sibling("tr")  # holds points + comments
                score = sub.select_one("span.score") if sub else None

                comments = 0
                if sub:
                    for anchor in sub.select("td.subtext a"):
                        text = self.safe_text(anchor)
                        match = re.search(r"(\d+)\s*comment", text)
                        if match:
                            comments = int(match.group(1))
                            break

                records.append(
                    {
                        "rank": self._first_int(self.safe_text(row.select_one("span.rank"))),
                        "title": self.safe_text(title_link),
                        "link": urljoin(BASE, href) if href else "",
                        "points": self._first_int(self.safe_text(score)),
                        "comments": comments,
                    }
                )
            except Exception:
                self.logger.exception("Skipping a malformed HN row")
        return records

    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Follow the 'More' link at the bottom of the page."""
        return self.next_link(html, current_url, "a.morelink")
