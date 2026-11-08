"""Unit tests for utils.cleaner.DataCleaner."""

import pytest

from utils.cleaner import DataCleaner


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Â£51.77", 51.77),
        ("£51.77", 51.77),
        ("£1,234.50", 1234.5),
        ("Price: 20", 20.0),
        ("free", None),
        ("", None),
        (None, None),
        (12, 12.0),
    ],
)
def test_parse_price(raw, expected):
    assert DataCleaner.parse_price(raw) == expected


def test_clean_text_collapses_whitespace_and_nbsp():
    assert DataCleaner.clean_text("  Hello \n\xa0 world  ") == "Hello world"


def test_clean_text_removes_mojibake_and_handles_none():
    assert DataCleaner.clean_text("Â£10") == "£10"
    assert DataCleaner.clean_text(None) == ""


@pytest.mark.parametrize(
    "value, expected",
    [("Three", 3), (["star-rating", "Five"], 5), ("one", 1), ("nonsense", 0), (None, 0)],
)
def test_star_rating_to_number(value, expected):
    assert DataCleaner.star_rating_to_number(value) == expected


def test_remove_duplicates_by_key_and_by_all_fields():
    rows = [{"u": 1, "t": "a"}, {"u": 1, "t": "b"}, {"u": 2, "t": "a"}]
    assert len(DataCleaner.remove_duplicates(rows, ["u"])) == 2
    assert len(DataCleaner.remove_duplicates(rows + rows)) == 3


def test_filter_records_all_filters():
    rows = [
        {"title": "Python Tricks", "price": 10.0, "rating": 5, "tags": ["code"]},
        {"title": "Cooking", "price": 30.0, "rating": 4, "tags": ["food"]},
        {"title": "Python Cooking", "price": 15.0, "rating": 2, "tags": []},
    ]
    assert len(DataCleaner.filter_records(rows, keyword="python")) == 2
    assert len(DataCleaner.filter_records(rows, keyword="food")) == 1  # searches list fields
    assert len(DataCleaner.filter_records(rows, max_price=15)) == 2
    assert len(DataCleaner.filter_records(rows, min_rating=4)) == 2
    assert [r["title"] for r in DataCleaner.filter_records(rows, "python", 20, 3)] == ["Python Tricks"]


def test_filter_excludes_records_missing_the_field():
    assert DataCleaner.filter_records([{"title": "x"}], max_price=10) == []
