# Multi-Site Web Scraper

A command-line scraper built with `requests` + `BeautifulSoup` for **legal practice sites**
(books.toscrape.com, quotes.toscrape.com), Hacker News, and the official GitHub API,
plus an SQLite price tracker with alerts and a scheduler. No API keys needed.

## Setup
```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
Requires Python 3.10+.

## Usage
```bash
python main.py books --pages 3 --export excel
python main.py books --max-price 20 --min-rating 4 --no-details
python main.py quotes --tag love --export csv json
python main.py hackernews --limit 20
python main.py github --user octocat --export html
python main.py track --url "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html" --alert 60
python main.py track --history
python main.py track --url <book-url> --alert 60 --schedule 60     # re-check hourly
```
Notes:
* `--pages 0` means *all* pages. Default is 1 page.
* For books, category requires visiting each book page (1-2 s each, politely). Use `--no-details` for speed.
* Output files are written to `data/`; the log is `data/scraper.log`.

## Tests
```bash
python -m pytest -v
```

## Ethical scraping
Only scrape sites that allow it; obey robots.txt (built in); keep delays; identify yourself;
prefer official APIs; never bypass logins/paywalls or collect personal data.
