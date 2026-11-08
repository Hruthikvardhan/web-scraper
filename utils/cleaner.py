"""Data cleaning helpers: text, prices, star ratings, duplicates and filters."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional, Sequence

Record = dict[str, Any]

STAR_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}
_PRICE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# "Â" appears when UTF-8 "£" is wrongly decoded as Latin-1 ("Â£", "Â ")
_MOJIBAKE_RE = re.compile(r"Â(?=[£\xa0\s])")


class DataCleaner:
    """Collection of static cleaning utilities (no state needed)."""

    @staticmethod
    def clean_text(text: Optional[Any]) -> str:
        """Normalise unicode, drop mojibake, collapse whitespace.

        >>> DataCleaner.clean_text("  Hello \\n\\xa0 world ")
        'Hello world'
        """
        if text is None:
            return ""
        value = _MOJIBAKE_RE.sub("", str(text))
        value = unicodedata.normalize("NFKC", value)  # nbsp -> normal space
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def parse_price(text: Optional[Any]) -> Optional[float]:
        """Convert a price string such as ``"Â£51.77"`` to ``51.77``.

        Returns ``None`` when no number can be found.
        """
        if text is None:
            return None
        if isinstance(text, (int, float)):
            return float(text)
        match = _PRICE_RE.search(str(text))
        if not match:
            return None
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def star_rating_to_number(value: Optional[Any]) -> int:
        """Convert ``"Three"`` or ``["star-rating", "Three"]`` to ``3`` (0 if unknown)."""
        if value is None:
            return 0
        tokens = value if isinstance(value, (list, tuple)) else str(value).split()
        for token in tokens:
            number = STAR_WORDS.get(str(token).strip().lower())
            if number is not None:
                return number
        return 0

    @staticmethod
    def clean_record(record: Record) -> Record:
        """Return a copy of ``record`` with every string value cleaned."""
        cleaned: Record = {}
        for key, value in record.items():
            if isinstance(value, str):
                cleaned[key] = DataCleaner.clean_text(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    DataCleaner.clean_text(v) if isinstance(v, str) else v for v in value
                ]
            else:
                cleaned[key] = value
        return cleaned

    @staticmethod
    def remove_duplicates(
        records: Iterable[Record], key_fields: Optional[Sequence[str]] = None
    ) -> list[Record]:
        """Drop duplicate records, keeping the first occurrence.

        Args:
            records: Records to de-duplicate.
            key_fields: Fields that define identity. ``None`` compares all fields.
        """
        seen: set[tuple] = set()
        unique: list[Record] = []
        for record in records:
            if key_fields:
                key = tuple(str(record.get(f)) for f in key_fields)
            else:
                key = tuple(sorted((k, str(v)) for k, v in record.items()))
            if key not in seen:
                seen.add(key)
                unique.append(record)
        return unique

    @staticmethod
    def filter_records(
        records: Iterable[Record],
        keyword: Optional[str] = None,
        max_price: Optional[float] = None,
        min_rating: Optional[int] = None,
    ) -> list[Record]:
        """Filter by keyword (any field), maximum price and minimum rating.

        A record missing the field being filtered is excluded.
        """
        result: list[Record] = []
        needle = keyword.lower().strip() if keyword else None
        for record in records:
            if needle:
                haystack = " ".join(
                    ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
                    for v in record.values()
                ).lower()
                if needle not in haystack:
                    continue
            if max_price is not None:
                price = record.get("price")
                if price is None or price > max_price:
                    continue
            if min_rating is not None:
                rating = record.get("rating")
                if rating is None or rating < min_rating:
                    continue
            result.append(record)
        return result
