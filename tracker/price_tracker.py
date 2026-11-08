"""SQLite-backed price tracker with a watch-list and price-drop alerts."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from utils.logger import get_logger

Record = dict[str, Any]
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "prices.db"


class PriceTracker:
    """Store price snapshots with timestamps and raise alerts below a threshold."""

    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("PriceTracker")
        self._init_db()

    # ------------------------------------------------------------------ database
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables on first use."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS price_history (
                       id         INTEGER PRIMARY KEY AUTOINCREMENT,
                       url        TEXT NOT NULL,
                       title      TEXT,
                       price      REAL NOT NULL,
                       checked_at TEXT NOT NULL)"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_history_url ON price_history(url)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS watchlist (
                       url         TEXT PRIMARY KEY,
                       alert_below REAL,
                       added_at    TEXT NOT NULL)"""
            )

    # ------------------------------------------------------------------ watch-list
    def add_to_watchlist(self, url: str, alert_below: Optional[float] = None) -> None:
        """Start tracking ``url``; a new threshold replaces the old one."""
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO watchlist (url, alert_below, added_at) VALUES (?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       alert_below = COALESCE(excluded.alert_below, watchlist.alert_below)""",
                (url, alert_below, now),
            )

    def get_watchlist(self) -> list[Record]:
        """All tracked URLs with their alert thresholds."""
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT url, alert_below, added_at FROM watchlist ORDER BY added_at").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ prices
    def save_price(
        self, url: str, title: str, price: float, checked_at: Optional[str] = None
    ) -> int:
        """Insert one price snapshot and return its row id."""
        stamp = checked_at or datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO price_history (url, title, price, checked_at) VALUES (?, ?, ?, ?)",
                (url, title, float(price), stamp),
            )
            row_id = cursor.lastrowid
        self.logger.info("Saved price %.2f for %s", price, url)
        return int(row_id or 0)

    def get_history(self, url: Optional[str] = None) -> list[Record]:
        """Price snapshots, oldest first. Pass ``url`` to restrict to one product."""
        query = "SELECT url, title, price, checked_at FROM price_history"
        params: tuple = ()
        if url:
            query += " WHERE url = ?"
            params = (url,)
        query += " ORDER BY url, checked_at, id"
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_latest_price(self, url: str) -> Optional[Record]:
        """Most recent snapshot for ``url`` (or ``None``)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT url, title, price, checked_at FROM price_history "
                "WHERE url = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
                (url,),
            ).fetchone()
        return dict(row) if row else None

    def check_alerts(self) -> list[Record]:
        """Watched products whose latest price is *below* their alert threshold."""
        alerts: list[Record] = []
        for item in self.get_watchlist():
            threshold = item["alert_below"]
            if threshold is None:
                continue
            latest = self.get_latest_price(item["url"])
            if latest and latest["price"] < threshold:
                alerts.append(
                    {
                        "url": item["url"],
                        "title": latest["title"],
                        "price": latest["price"],
                        "threshold": threshold,
                    }
                )
        return alerts

    def track_all(self, fetch_product: Callable[[str], Optional[Record]]) -> list[Record]:
        """Fetch every watched product via ``fetch_product`` and save its price.

        Args:
            fetch_product: Function taking a URL and returning a dict with at least
                ``title`` and ``price`` (``None`` on failure).

        Returns:
            One result dict per product: url, title, price, previous (or None).
        """
        results: list[Record] = []
        for item in self.get_watchlist():
            url = item["url"]
            product = fetch_product(url)
            if not product or product.get("price") is None:
                self.logger.error("No price obtained for %s", url)
                continue
            previous = self.get_latest_price(url)
            self.save_price(url, product.get("title", ""), product["price"])
            results.append(
                {
                    "url": url,
                    "title": product.get("title", ""),
                    "price": product["price"],
                    "previous": previous["price"] if previous else None,
                }
            )
        return results
