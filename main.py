#!/usr/bin/env python3
"""Multi-site practice web scraper - command line entry point.

Examples:
    python main.py books --pages 3 --export excel
    python main.py quotes --tag love --export csv
    python main.py hackernews --limit 20
    python main.py github --user octocat
    python main.py track --url <book-url> --alert 30
    python main.py track --history
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

import schedule
from colorama import Fore, Style, init as colorama_init

from scrapers.books_scraper import BooksScraper
from scrapers.github_scraper import GitHubScraper
from scrapers.hackernews_scraper import HackerNewsScraper
from scrapers.quotes_scraper import QuotesScraper
from tracker.price_tracker import PriceTracker
from utils.cleaner import DataCleaner
from utils.exporter import DataExporter
from utils.logger import LOG_FILE, get_logger

Record = dict[str, Any]
logger = get_logger("main")


# ---------------------------------------------------------------------- console helpers
def info(msg: str) -> None:
    print(f"{Fore.CYAN}[i]{Style.RESET_ALL} {msg}")


def ok(msg: str) -> None:
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {msg}")


def warn(msg: str) -> None:
    print(f"{Fore.YELLOW}[!]{Style.RESET_ALL} {msg}")


def fail(msg: str) -> None:
    print(f"{Fore.RED}[x]{Style.RESET_ALL} {msg}")


def print_table(records: list[Record], columns: Sequence[str], limit: int = 10, width: int = 36) -> None:
    """Print the first ``limit`` records as an aligned text table."""
    if not records:
        return

    def fmt(value: Any) -> str:
        text = ", ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
        return text if len(text) <= width else text[: width - 3] + "..."

    shown = records[:limit]
    widths = [min(width, max(len(c), *(len(fmt(r.get(c, ""))) for r in shown))) for c in columns]
    header = "  ".join(c.upper().ljust(w) for c, w in zip(columns, widths))
    print(f"\n{Style.BRIGHT}{Fore.CYAN}{header}{Style.RESET_ALL}")
    print("-" * len(header))
    for record in shown:
        print("  ".join(fmt(record.get(c, "")).ljust(w) for c, w in zip(columns, widths)))
    if len(records) > limit:
        print(f"{Style.DIM}... and {len(records) - limit} more (use --export to save everything){Style.RESET_ALL}")
    print()


def export_records(records: list[Record], formats: Optional[list[str]], name: str) -> None:
    """Export ``records`` in every requested format and print the saved paths."""
    if not formats:
        return
    exporter = DataExporter()
    writers = {
        "csv": exporter.to_csv,
        "excel": exporter.to_excel,
        "json": exporter.to_json,
        "html": lambda recs, n: exporter.to_html_report(recs, n, title=f"{name.title()} report"),
    }
    for fmt in formats:
        try:
            path = writers[fmt](records, name)
            if path:
                ok(f"Saved {fmt.upper()} -> {path}")
        except Exception as exc:  # e.g. file open in Excel -> PermissionError
            logger.exception("Export to %s failed", fmt)
            fail(f"Could not export {fmt}: {exc}")


def money(value: Optional[float]) -> str:
    return f"£{value:.2f}" if value is not None else "n/a"


# ---------------------------------------------------------------------- commands
def cmd_books(args: argparse.Namespace) -> int:
    info("Scraping books.toscrape.com ...")
    if args.pages == 0 and not args.no_details:
        warn("All 50 pages with category lookup = ~1000 requests (~25 min). Add --no-details to go faster.")
    scraper = BooksScraper(
        fetch_details=not args.no_details, max_price=args.max_price, min_rating=args.min_rating
    )
    records = scraper.scrape(max_pages=args.pages or None)
    records = DataCleaner.filter_records(records, keyword=args.keyword)
    if not records:
        warn(scraper.last_error or "No books matched your filters.")
        return 1
    ok(f"{len(records)} books found")
    print_table(records, ["title", "price", "rating", "category", "availability"])
    export_records(records, args.export, "books")
    return 0


def cmd_quotes(args: argparse.Namespace) -> int:
    info("Scraping quotes.toscrape.com" + (f" (tag: {args.tag})" if args.tag else "") + " ...")
    scraper = QuotesScraper(tag=args.tag)
    records = scraper.scrape(max_pages=args.pages or None)
    records = DataCleaner.filter_records(records, keyword=args.keyword)
    if not records:
        warn(scraper.last_error or "No quotes found.")
        return 1
    ok(f"{len(records)} quotes found")
    print_table(records, ["text", "author", "tags"], width=50)
    export_records(records, args.export, "quotes")
    return 0


def cmd_hackernews(args: argparse.Namespace) -> int:
    info("Scraping the Hacker News front page ...")
    scraper = HackerNewsScraper()
    pages = max(1, math.ceil(args.limit / 30))  # HN shows 30 stories per page
    if pages > 1:
        warn("HN's robots.txt requests a long Crawl-delay; page 2+ will take a while.")
    records = scraper.scrape(max_pages=pages, limit=args.limit)
    records = DataCleaner.filter_records(records, keyword=args.keyword)
    if not records:
        warn(scraper.last_error or "No stories found.")
        return 1
    ok(f"{len(records)} stories found")
    print_table(records, ["rank", "title", "points", "comments"], limit=args.limit, width=60)
    export_records(records, args.export, "hackernews")
    return 0


def cmd_github(args: argparse.Namespace) -> int:
    info(f"Fetching GitHub profile for '{args.user}' ...")
    scraper = GitHubScraper(args.user)
    records = scraper.scrape()
    if not records:
        fail(scraper.last_error or "Could not fetch the profile.")
        return 1
    profile = records[0]
    print()
    for key, value in profile.items():
        print(f"  {Fore.CYAN}{key.replace('_', ' ').title():<14}{Style.RESET_ALL} {value}")
    print()
    export_records(records, args.export, f"github_{args.user}")
    return 0


def _is_book_url(url: str) -> bool:
    parts = urlparse(url)
    return parts.scheme in ("http", "https") and parts.netloc == "books.toscrape.com"


def run_tracking_job(tracker: PriceTracker, scraper: BooksScraper) -> None:
    """Check every watched book once and print prices plus alerts."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    info(f"Price check started at {stamp}")
    results = tracker.track_all(scraper.fetch_product)
    if not results:
        warn(scraper.last_error or "No prices could be collected (see data/scraper.log).")
        return
    for r in results:
        change = ""
        if r["previous"] is not None and r["previous"] != r["price"]:
            colour = Fore.GREEN if r["price"] < r["previous"] else Fore.RED
            change = f" {colour}(was {money(r['previous'])}){Style.RESET_ALL}"
        ok(f"{r['title'][:50]}: {money(r['price'])}{change}")
    for alert in tracker.check_alerts():
        print(
            f"{Style.BRIGHT}{Fore.RED}*** PRICE ALERT ***{Style.RESET_ALL} "
            f"{alert['title']} is {money(alert['price'])}, below your limit of {money(alert['threshold'])}!"
        )


def show_history(tracker: PriceTracker, url: Optional[str]) -> None:
    """Print stored price history grouped by product."""
    history = tracker.get_history(url)
    if not history:
        warn("No price history yet. Run: python main.py track --url <book-url> --alert 30")
        return
    current_url, previous = None, None
    for row in history:
        if row["url"] != current_url:
            current_url, previous = row["url"], None
            print(f"\n{Style.BRIGHT}{row['title']}{Style.RESET_ALL}\n{Style.DIM}{row['url']}{Style.RESET_ALL}")
            print(f"  {'DATE':<20} {'PRICE':>8}  CHANGE")
        delta = ""
        if previous is not None and row["price"] != previous:
            diff = row["price"] - previous
            colour = Fore.GREEN if diff < 0 else Fore.RED
            delta = f"{colour}{diff:+.2f}{Style.RESET_ALL}"
        print(f"  {row['checked_at']:<20} {money(row['price']):>8}  {delta}")
        previous = row["price"]
    print()


def cmd_track(args: argparse.Namespace) -> int:
    tracker = PriceTracker()
    if args.history:
        show_history(tracker, args.url)
        return 0

    if args.alert is not None and not args.url:
        fail("--alert needs --url (which book should the alert apply to?)")
        return 2
    if args.url:
        if not _is_book_url(args.url):
            fail("Please give a books.toscrape.com product URL.")
            return 2
        tracker.add_to_watchlist(args.url, args.alert)
        if args.alert is not None:
            info(f"Alert set: notify when price drops below {money(args.alert)}")
    if not tracker.get_watchlist():
        warn("Watch-list is empty. Add a book with: python main.py track --url <book-url> --alert 30")
        return 1

    scraper = BooksScraper(fetch_details=False)
    job = lambda: run_tracking_job(tracker, scraper)  # noqa: E731
    job()
    if args.schedule:
        if args.schedule <= 0:
            fail("--schedule must be a positive number of minutes")
            return 2
        schedule.every(args.schedule).minutes.do(job)
        info(f"Re-checking every {args.schedule} minute(s). Press Ctrl+C to stop.")
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            ok("Scheduler stopped.")
    return 0


# ---------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    """Create the argparse command tree."""
    parser = argparse.ArgumentParser(
        prog="main.py", description="Multi-site practice web scraper (books, quotes, HN, GitHub, prices)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--export", nargs="+", choices=["csv", "excel", "json", "html"],
                        help="Save results in one or more formats (data/ folder)")
    common.add_argument("--keyword", help="Keep only records containing this word")

    p = sub.add_parser("books", parents=[common], help="Scrape books.toscrape.com")
    p.add_argument("--pages", type=int, default=1, help="Pages to scrape (0 = all 50, default 1)")
    p.add_argument("--max-price", type=float, help="Maximum price in GBP")
    p.add_argument("--min-rating", type=int, choices=range(1, 6), help="Minimum star rating (1-5)")
    p.add_argument("--no-details", action="store_true", help="Skip per-book pages (faster, no category)")
    p.set_defaults(func=cmd_books)

    p = sub.add_parser("quotes", parents=[common], help="Scrape quotes.toscrape.com")
    p.add_argument("--tag", help="Only quotes with this tag, e.g. love")
    p.add_argument("--pages", type=int, default=1, help="Pages to scrape (0 = all, default 1)")
    p.set_defaults(func=cmd_quotes)

    p = sub.add_parser("hackernews", parents=[common], help="Scrape the Hacker News front page")
    p.add_argument("--limit", type=int, default=30, help="Number of stories (default 30)")
    p.set_defaults(func=cmd_hackernews)

    p = sub.add_parser("github", parents=[common], help="GitHub profile summary via the API")
    p.add_argument("--user", required=True, help="GitHub username")
    p.set_defaults(func=cmd_github)

    p = sub.add_parser("track", help="Track book prices and alert on drops")
    p.add_argument("--url", help="books.toscrape.com product URL")
    p.add_argument("--alert", type=float, help="Alert when price drops below this value (GBP)")
    p.add_argument("--history", action="store_true", help="Show stored price history")
    p.add_argument("--schedule", type=int, metavar="MINUTES", help="Repeat the check every N minutes")
    p.set_defaults(func=cmd_track)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Program entry point; returns a process exit code."""
    colorama_init(autoreset=False)
    for stream in (sys.stdout, sys.stderr):  # avoid UnicodeEncodeError on legacy consoles
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logger.info("Command: %s", " ".join(sys.argv[1:]))
    try:
        return args.func(args)
    except KeyboardInterrupt:
        warn("Interrupted by user.")
        return 130
    except Exception as exc:  # last line of defence: log the traceback, show a friendly message
        logger.exception("Unhandled error")
        fail(f"Unexpected error: {exc}  (details in {LOG_FILE})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
