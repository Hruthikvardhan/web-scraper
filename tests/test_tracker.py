"""Tests for the SQLite price tracker."""

from tracker.price_tracker import PriceTracker

URL = "https://books.toscrape.com/catalogue/x_1/index.html"


def test_history_and_alerts(tmp_path):
    tracker = PriceTracker(tmp_path / "prices.db")
    tracker.add_to_watchlist(URL, alert_below=30)
    tracker.save_price(URL, "Book X", 40.0, "2025-01-01T10:00:00")
    tracker.save_price(URL, "Book X", 35.0, "2025-01-02T10:00:00")
    assert [h["price"] for h in tracker.get_history(URL)] == [40.0, 35.0]
    assert tracker.check_alerts() == []              # 35 is not below 30
    tracker.save_price(URL, "Book X", 29.99, "2025-01-03T10:00:00")
    alerts = tracker.check_alerts()
    assert len(alerts) == 1 and alerts[0]["price"] == 29.99


def test_track_all_uses_fetcher_and_keeps_threshold(tmp_path):
    tracker = PriceTracker(tmp_path / "prices.db")
    tracker.add_to_watchlist(URL, alert_below=30)
    tracker.add_to_watchlist(URL)                    # re-adding without threshold keeps old one
    assert tracker.get_watchlist()[0]["alert_below"] == 30
    results = tracker.track_all(lambda u: {"title": "Book X", "price": 20.0})
    assert results[0]["previous"] is None and results[0]["price"] == 20.0
    assert len(tracker.check_alerts()) == 1
    assert tracker.track_all(lambda u: None) == []   # failed fetch is skipped, no crash
