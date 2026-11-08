"""Abstract base class shared by every scraper in the project.

Responsibilities handled here so subclasses stay tiny:
  * a ``requests.Session`` with a descriptive User-Agent
  * robots.txt checking (including ``Crawl-delay``)
  * polite random delays between requests
  * retries with exponential backoff
  * a template method (``scrape``) that runs fetch -> parse -> clean -> enrich
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from tqdm import tqdm

from utils.cleaner import DataCleaner
from utils.logger import get_logger

Record = dict[str, Any]


class BaseScraper(ABC):
    """Template for all scrapers. Subclasses implement ``parse_page``."""

    #: Short name used in progress bars and logs
    name: str = "base"
    #: First URL to fetch when ``scrape()`` is called
    start_url: str = ""
    #: Fields that identify a unique record (``None`` = compare every field)
    dedupe_keys: Optional[tuple[str, ...]] = None

    USER_AGENT = "Mozilla/5.0 (compatible; PracticeScraper/1.0; educational use)"
    ROBOTS_AGENT = "PracticeScraper"  # token matched against robots.txt rules

    def __init__(
        self,
        delay_range: tuple[float, float] = (1.0, 2.0),
        timeout: int = 10,
        max_retries: int = 3,
        respect_robots: bool = True,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": self.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        )
        self.delay_range = delay_range
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.respect_robots = respect_robots
        self.last_error: Optional[str] = None  # human readable reason of last failure
        self.logger = get_logger(self.__class__.__name__)
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}
        self._crawl_delays: dict[str, float] = {}
        self._last_request_at: Optional[float] = None

    # ------------------------------------------------------------------ robots.txt
    @staticmethod
    def _origin(url: str) -> str:
        parts = urlparse(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _load_robots(self, origin: str) -> Optional[RobotFileParser]:
        """Download and parse robots.txt. ``None`` means 'no usable rules' (allow)."""
        robots_url = f"{origin}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
        except requests.RequestException as exc:
            self.logger.warning("Could not read %s (%s); assuming allowed", robots_url, exc)
            return None
        if response.status_code != 200:
            self.logger.info("%s returned HTTP %s; assuming allowed", robots_url, response.status_code)
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        delay = parser.crawl_delay(self.ROBOTS_AGENT)
        if delay:
            self._crawl_delays[origin] = float(delay)
            self.logger.info("robots.txt for %s asks for Crawl-delay %ss", origin, delay)
        return parser

    def check_robots_txt(self, url: str) -> bool:
        """Return True if robots.txt allows our user agent to fetch ``url``."""
        if not self.respect_robots:
            return True
        origin = self._origin(url)
        if origin not in self._robots_cache:
            self._robots_cache[origin] = self._load_robots(origin)
        parser = self._robots_cache[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.ROBOTS_AGENT, url)

    # ------------------------------------------------------------------ networking
    def _rate_limit(self, url: str) -> None:
        """Sleep so consecutive requests are 1-2 s apart (or the Crawl-delay)."""
        if self._last_request_at is None:
            return
        delay = random.uniform(*self.delay_range)
        delay = max(delay, self._crawl_delays.get(self._origin(url), 0.0))
        wait = delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _request(
        self, url: str, params: Optional[dict[str, Any]] = None
    ) -> Optional[requests.Response]:
        """GET ``url`` with robots check, rate limit, retries and backoff."""
        self.last_error = None
        if not self.check_robots_txt(url):
            self.last_error = f"Blocked by robots.txt: {url}"
            self.logger.warning(self.last_error)
            return None

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit(url)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                # requests guesses Latin-1 for text/* without charset -> "Â£" bugs
                if response.encoding is None or response.encoding.lower() in ("iso-8859-1", "latin-1"):
                    response.encoding = "utf-8"
                return response
            except requests.exceptions.HTTPError as exc:
                self._last_request_at = time.monotonic()
                status = exc.response.status_code if exc.response is not None else None
                self.last_error = f"HTTP {status} for {url}"
                if exc.response is not None and exc.response.headers.get("X-RateLimit-Remaining") == "0":
                    self.last_error = "GitHub API rate limit reached - try again later"
                self.logger.error("Attempt %d/%d: %s", attempt, self.max_retries, self.last_error)
                # Client errors (404, 403...) will not fix themselves, except 408/429
                if status is not None and 400 <= status < 500 and status not in (408, 429):
                    return None
            except requests.exceptions.Timeout:
                self._last_request_at = time.monotonic()
                self.last_error = f"Timeout after {self.timeout}s for {url}"
                self.logger.error("Attempt %d/%d: %s", attempt, self.max_retries, self.last_error)
            except requests.exceptions.ConnectionError as exc:
                self._last_request_at = time.monotonic()
                self.last_error = f"Connection error for {url}"
                self.logger.error("Attempt %d/%d: %s (%s)", attempt, self.max_retries, self.last_error, exc)
            except requests.exceptions.RequestException as exc:
                self._last_request_at = time.monotonic()
                self.last_error = f"Request failed for {url}: {exc}"
                self.logger.error("Attempt %d/%d: %s", attempt, self.max_retries, self.last_error)

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)  # exponential backoff: 2s, 4s, ...
        return None

    def fetch_page(self, url: str, params: Optional[dict[str, Any]] = None) -> Optional[str]:
        """Return the response body as text, or ``None`` after all retries fail."""
        response = self._request(url, params)
        return response.text if response is not None else None

    def fetch_json(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Return parsed JSON, or ``None`` on network or decoding errors."""
        response = self._request(url, params)
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            self.last_error = f"Invalid JSON from {url}"
            self.logger.error(self.last_error)
            return None

    # ------------------------------------------------------------------ parsing helpers
    @staticmethod
    def safe_text(node: Optional[Tag], default: str = "") -> str:
        """Cleaned text of a tag, or ``default`` if the tag is missing."""
        if node is None:
            return default
        return DataCleaner.clean_text(node.get_text(" ")) or default

    @staticmethod
    def safe_attr(node: Optional[Tag], attr: str, default: str = "") -> str:
        """Attribute value of a tag, or ``default`` if tag/attribute is missing."""
        if node is None:
            return default
        value = node.get(attr)
        if value is None:
            return default
        return " ".join(value) if isinstance(value, list) else str(value)

    @staticmethod
    def next_link(html: str, current_url: str, selector: str = "li.next a") -> Optional[str]:
        """Absolute URL of the 'next page' link matching ``selector`` (if any)."""
        link = BeautifulSoup(html, "lxml").select_one(selector)
        href = link.get("href") if link else None
        return urljoin(current_url, str(href)) if href else None

    # ------------------------------------------------------------------ hooks
    @abstractmethod
    def parse_page(self, html: str, page_url: str = "") -> list[Record]:
        """Turn one page of raw content into a list of record dicts."""

    def get_next_page_url(self, html: str, current_url: str) -> Optional[str]:
        """Return the URL of the next page, or ``None`` when finished."""
        return None

    def clean(self, records: list[Record]) -> list[Record]:
        """Clean strings and drop duplicates. Override to add more steps."""
        cleaned = [DataCleaner.clean_record(r) for r in records]
        return DataCleaner.remove_duplicates(cleaned, self.dedupe_keys)

    def enrich(self, records: list[Record]) -> list[Record]:
        """Optional extra step (e.g. visit detail pages). Default: no-op."""
        return records

    # ------------------------------------------------------------------ template method
    def scrape(
        self,
        max_pages: Optional[int] = None,
        limit: Optional[int] = None,
        show_progress: bool = True,
    ) -> list[Record]:
        """Fetch -> parse -> follow pagination -> clean -> enrich.

        Args:
            max_pages: Stop after this many pages (``None``/0 = follow all pages).
            limit: Stop after this many records (``None`` = no limit).
            show_progress: Show a tqdm progress bar.
        """
        raw: list[Record] = []
        url: Optional[str] = self.start_url
        pages = 0
        unlimited = not max_pages
        self.logger.info("Starting %s scrape at %s", self.name, url)

        with tqdm(
            total=None if unlimited else max_pages,
            desc=f"Scraping {self.name}",
            unit="page",
            disable=not show_progress,
            leave=False,
        ) as bar:
            while url and (unlimited or pages < max_pages):  # type: ignore[operator]
                html = self.fetch_page(url)
                if html is None:
                    break
                try:
                    raw.extend(self.parse_page(html, url))
                except Exception:  # never let one bad page kill the run
                    self.logger.exception("Parsing failed for %s", url)
                pages += 1
                bar.update(1)
                if limit and len(raw) >= limit:
                    break
                try:
                    url = self.get_next_page_url(html, url)
                except Exception:
                    self.logger.exception("Could not find next page after %s", url)
                    url = None

        records = self.clean(raw)
        if limit:
            records = records[:limit]
        records = self.enrich(records)
        self.logger.info("Finished %s scrape: %d records from %d pages", self.name, len(records), pages)
        return records
