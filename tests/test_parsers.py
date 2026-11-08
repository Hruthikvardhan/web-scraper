"""Parser tests using small saved HTML/JSON snippets (no network needed)."""

import json

from scrapers.books_scraper import BooksScraper
from scrapers.github_scraper import GitHubScraper
from scrapers.hackernews_scraper import HackerNewsScraper
from scrapers.quotes_scraper import QuotesScraper

FAST = {"delay_range": (0, 0), "max_retries": 1, "respect_robots": False}

BOOKS_LIST = """
<html><body><ol class="row">
<li><article class="product_pod">
  <p class="star-rating Three"></p>
  <h3><a href="catalogue/a-light-in-the-attic_1000/index.html" title="A Light in the Attic">A Light in the ...</a></h3>
  <div class="product_price"><p class="price_color">Â£51.77</p>
  <p class="instock availability"><i class="icon-ok"></i> In stock</p></div>
</article></li>
<li><article class="product_pod">
  <h3><a href="catalogue/broken_1/index.html">No rating, no price</a></h3>
</article></li>
</ol><ul class="pager"><li class="next"><a href="catalogue/page-2.html">next</a></li></ul></body></html>
"""

BOOKS_LIST_PAGE2 = """
<article class="product_pod"><p class="star-rating Five"></p>
<h3><a href="tipping-the-velvet_999/index.html" title="Tipping the Velvet">T</a></h3>
<p class="price_color">£53.74</p><p class="instock availability">In stock</p></article>
"""

BOOK_DETAIL = """
<html><body>
<ul class="breadcrumb"><li><a>Home</a></li><li><a>Books</a></li>
<li><a>Poetry</a></li><li class="active">A Light in the Attic</li></ul>
<div class="product_main"><h1>A Light in the Attic</h1>
<p class="price_color">£51.77</p>
<p class="instock availability">In stock (22 available)</p>
<p class="star-rating Three"></p></div></body></html>
"""

QUOTES = """
<div class="quote"><span class="text">\u201cThe world as we have created it.\u201d</span>
<span>by <small class="author">Albert Einstein</small></span>
<div class="tags"><a class="tag">change</a><a class="tag">world</a></div></div>
<div class="quote"><span class="text">\u201cNo author or tags here.\u201d</span></div>
<ul class="pager"><li class="next"><a href="/page/2/">Next</a></li></ul>
"""

HN = """
<table><tr class="athing" id="1"><td><span class="rank">1.</span></td>
<td><span class="titleline"><a href="https://example.com/a">Story A</a></span></td></tr>
<tr><td colspan="2"></td><td class="subtext"><span class="subline">
<span class="score">123 points</span> by <a class="hnuser">bob</a> | <a href="hide?id=1">hide</a> |
<a href="item?id=1">45&nbsp;comments</a></span></td></tr>
<tr class="athing" id="2"><td><span class="rank">2.</span></td>
<td><span class="titleline"><a href="item?id=2">Job post</a></span></td></tr>
<tr><td colspan="2"></td><td class="subtext"><span class="age">1 hour ago</span></td></tr>
</table><a class="morelink" href="?p=2">More</a>
"""


def test_books_listing_parses_and_survives_missing_tags():
    books = BooksScraper(fetch_details=False, **FAST).parse_page(BOOKS_LIST, "https://books.toscrape.com/")
    assert len(books) == 2
    first, broken = books
    assert first["title"] == "A Light in the Attic"
    assert first["price"] == 51.77 and first["rating"] == 3
    assert first["availability"] == "In stock"
    assert first["url"] == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert broken["price"] is None and broken["rating"] == 0  # missing tags did not crash


def test_book_detail_page_gives_category():
    detail = BooksScraper(**FAST).parse_product_page(BOOK_DETAIL, "http://x/book")
    assert detail["category"] == "Poetry"
    assert detail["price"] == 51.77 and detail["rating"] == 3
    assert "22 available" in detail["availability"]


def test_books_pagination_filters_and_dedupe(monkeypatch):
    scraper = BooksScraper(fetch_details=False, max_price=52, **FAST)
    pages = {
        "https://books.toscrape.com/": BOOKS_LIST,
        "https://books.toscrape.com/catalogue/page-2.html": BOOKS_LIST_PAGE2,
    }
    monkeypatch.setattr(scraper, "fetch_page", lambda url, params=None: pages.get(url))
    result = scraper.scrape(max_pages=5, show_progress=False)
    # 3 books parsed, one has no price (filtered by max_price), 53.74 > 52 filtered
    assert [b["title"] for b in result] == ["A Light in the Attic"]


def test_quotes_parser_and_next_link():
    scraper = QuotesScraper(**FAST)
    quotes = scraper.parse_page(QUOTES, "https://quotes.toscrape.com/")
    assert quotes[0] == {"text": "The world as we have created it.", "author": "Albert Einstein",
                         "tags": ["change", "world"]}
    assert quotes[1]["author"] == "" and quotes[1]["tags"] == []
    assert scraper.get_next_page_url(QUOTES, "https://quotes.toscrape.com/") == "https://quotes.toscrape.com/page/2/"


def test_quotes_tag_url():
    assert QuotesScraper(tag="love", **FAST).start_url == "https://quotes.toscrape.com/tag/love/"


def test_hackernews_parser():
    scraper = HackerNewsScraper(**FAST)
    stories = scraper.parse_page(HN)
    assert stories[0] == {"rank": 1, "title": "Story A", "link": "https://example.com/a",
                          "points": 123, "comments": 45}
    assert stories[1]["points"] == 0 and stories[1]["comments"] == 0  # job post: no score
    assert stories[1]["link"] == "https://news.ycombinator.com/item?id=2"
    assert scraper.get_next_page_url(HN, "https://news.ycombinator.com/") == "https://news.ycombinator.com/?p=2"


def test_github_repo_parsing_and_summary():
    scraper = GitHubScraper("octocat", **FAST)
    repos_json = json.dumps([
        {"name": "a", "stargazers_count": 10, "language": "Python", "fork": False},
        {"name": "b", "stargazers_count": 5, "language": "Python", "fork": False},
        {"name": "c", "stargazers_count": 1, "language": "Go", "fork": False},
        {"name": "d", "stargazers_count": 0, "language": "Rust", "fork": True},
        {"name": "e", "stargazers_count": None, "language": None},
    ])
    repos = scraper.parse_page(repos_json)
    summary = GitHubScraper.build_summary(
        {"login": "octocat", "name": None, "bio": None, "followers": 7, "public_repos": 5}, repos
    )
    assert summary["name"] == "octocat" and summary["total_stars"] == 16
    assert summary["top_languages"] == "Python (2), Go (1)"  # forks are ignored
    assert scraper.parse_page("not json") == []
