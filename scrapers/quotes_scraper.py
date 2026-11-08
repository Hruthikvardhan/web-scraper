"""Scraper for https://quotes.toscrape.com (a site built for scraping practice)."""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote as url_quote

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, Record

BASE = "https://quotes.toscrape.com"


class QuotesScraper(BaseScraper):
    """Extract quote text, author and tags, following pagination."""

    name = "quotes"
    dedupe_keys = ("text", "author")

    def __init__(self, tag: Optional[str] = None, **kwargs) -> None:
        """
        Args:
            tag: Only scrape quotes carrying this tag (e.g. ``"love"``).
        """
        super().__init__(**kwargs)
        self.tag = tag
        self.start_url = f"{BASE}/tag/{url_quote(tag.strip())}/" if tag else f"{BASE}/"

    def parse_page(self, html: str, page_url: str = "") -> list[Record]:
        """Parse one page of quotes."""
        soup = BeautifulSoup(html, "lxml")
        records: list[Record] = []
        for block in soup.select("div.quote"):
            try:
                text = self.safe_text(block.select_one("span.text")).strip("\u201c\u201d\"")
                records.append(
                    {
                        "text": text,
                        "author": self.safe_text(block.select_one("small.author")),
                        "tags": [self.safe_text(t) for t in block.select("a.tag") if self.safe_text(t)],
                    }
                )
            except Exception:
                self.logger.exception("Skipping a malformed quote on %s", page_url)
        return records

    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Follow the 'Next' button."""
        return self.next_link(html, current_url, "li.next a")
