"""Scraper for https://books.toscrape.com (a site built for scraping practice)."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from tqdm import tqdm

from scrapers.base_scraper import BaseScraper, Record
from utils.cleaner import DataCleaner


class BooksScraper(BaseScraper):
    """Extract title, price, rating, availability, category and URL of every book."""

    name = "books"
    start_url = "https://books.toscrape.com/"
    dedupe_keys = ("url",)

    def __init__(
        self,
        fetch_details: bool = True,
        max_price: Optional[float] = None,
        min_rating: Optional[int] = None,
        **kwargs,
    ) -> None:
        """
        Args:
            fetch_details: Visit each product page to get the category (slower).
            max_price: Drop books more expensive than this *before* fetching details.
            min_rating: Drop books rated lower than this *before* fetching details.
        """
        super().__init__(**kwargs)
        self.fetch_details = fetch_details
        self.max_price = max_price
        self.min_rating = min_rating

    # ------------------------------------------------------------------ parsing
    def parse_page(self, html: str, page_url: str = "") -> list[Record]:
        """Parse one catalogue listing page into book records."""
        soup = BeautifulSoup(html, "lxml")
        records: list[Record] = []
        for card in soup.select("article.product_pod"):
            try:
                link = card.select_one("h3 a")
                href = self.safe_attr(link, "href")
                rating_tag = card.select_one("p.star-rating")
                records.append(
                    {
                        "title": self.safe_attr(link, "title") or self.safe_text(link),
                        "price": DataCleaner.parse_price(self.safe_text(card.select_one("p.price_color"))),
                        "rating": DataCleaner.star_rating_to_number(
                            rating_tag.get("class") if rating_tag else None
                        ),
                        "availability": self.safe_text(card.select_one("p.availability")),
                        "category": "Unknown",
                        "url": urljoin(page_url, href) if href else "",
                    }
                )
            except Exception:
                self.logger.exception("Skipping a malformed book card on %s", page_url)
        return records

    def parse_product_page(self, html: str, page_url: str = "") -> Record:
        """Parse a single product page (used for categories and price tracking)."""
        soup = BeautifulSoup(html, "lxml")
        crumbs = [self.safe_text(li) for li in soup.select("ul.breadcrumb li")]
        # Breadcrumb is: Home > Books > <Category> > <Title>
        category = crumbs[-2] if len(crumbs) >= 3 else "Unknown"
        main = soup.select_one("div.product_main")
        rating_tag = main.select_one("p.star-rating") if main else None
        return {
            "title": self.safe_text(main.select_one("h1") if main else None),
            "price": DataCleaner.parse_price(
                self.safe_text(main.select_one("p.price_color") if main else None)
            ),
            "rating": DataCleaner.star_rating_to_number(
                rating_tag.get("class") if rating_tag else None
            ),
            "availability": self.safe_text(main.select_one("p.availability") if main else None),
            "category": category,
            "url": page_url,
        }

    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Follow the 'next' button of the pagination bar."""
        return self.next_link(html, current_url, "li.next a")

    # ------------------------------------------------------------------ pipeline hooks
    def clean(self, records: list[Record]) -> list[Record]:
        """Standard cleaning + the cheap price/rating filters (before enrichment)."""
        cleaned = super().clean(records)
        return DataCleaner.filter_records(
            cleaned, max_price=self.max_price, min_rating=self.min_rating
        )

    def enrich(self, records: list[Record]) -> list[Record]:
        """Visit each product page to fill in the real category and stock count."""
        if not self.fetch_details:
            return records
        for record in tqdm(records, desc="Fetching categories", unit="book", leave=False):
            html = self.fetch_page(record["url"]) if record.get("url") else None
            if html is None:
                continue
            try:
                detail = self.parse_product_page(html, record["url"])
                record["category"] = detail["category"]
                record["availability"] = detail["availability"] or record["availability"]
            except Exception:
                self.logger.exception("Could not parse product page %s", record.get("url"))
        return records

    def fetch_product(self, url: str) -> Optional[Record]:
        """Fetch and parse a single product page (used by the price tracker)."""
        html = self.fetch_page(url)
        if html is None:
            return None
        try:
            return self.parse_product_page(html, url)
        except Exception:
            self.logger.exception("Could not parse product page %s", url)
            return None
