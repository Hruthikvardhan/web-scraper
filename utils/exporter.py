"""Export scraped records to CSV, Excel, JSON and an HTML report."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from utils.logger import get_logger

Record = dict[str, Any]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"


class DataExporter:
    """Write a list of dict records to several file formats."""

    def __init__(self, output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("DataExporter")

    # ------------------------------------------------------------------ helpers
    def _path(self, name: str, extension: str) -> Path:
        """Build a timestamped, filesystem-safe output path."""
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "export"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.output_dir / f"{safe}_{stamp}.{extension}"

    @staticmethod
    def _flatten(records: list[Record]) -> pd.DataFrame:
        """Turn records into a DataFrame, joining list values with commas."""
        rows = [
            {k: (", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v)
             for k, v in record.items()}
            for record in records
        ]
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ exports
    def to_csv(self, records: list[Record], name: str = "export") -> Optional[Path]:
        """Save records to a UTF-8 CSV file (BOM added so Excel reads £ correctly)."""
        if not records:
            return None
        path = self._path(name, "csv")
        self._flatten(records).to_csv(path, index=False, encoding="utf-8-sig")
        self.logger.info("Exported %d records to %s", len(records), path)
        return path

    def to_excel(self, records: list[Record], name: str = "export") -> Optional[Path]:
        """Save records to .xlsx with a styled header, frozen pane and auto widths."""
        if not records:
            return None
        path = self._path(name, "xlsx")
        df = self._flatten(records)
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Data")
            sheet = writer.sheets["Data"]
            fill = PatternFill("solid", start_color="1F4E78", end_color="1F4E78")
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = fill
                cell.alignment = Alignment(horizontal="center", vertical="center")
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for idx, column in enumerate(df.columns, start=1):
                longest = max([len(str(column))] + [len(str(v)) for v in df[column]])
                sheet.column_dimensions[get_column_letter(idx)].width = min(longest + 2, 60)
        self.logger.info("Exported %d records to %s", len(records), path)
        return path

    def to_json(self, records: list[Record], name: str = "export") -> Optional[Path]:
        """Save records to a pretty-printed JSON file."""
        if not records:
            return None
        path = self._path(name, "json")
        path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        self.logger.info("Exported %d records to %s", len(records), path)
        return path

    def to_html_report(
        self, records: list[Record], name: str = "export", title: str = "Scrape Report"
    ) -> Optional[Path]:
        """Save a self-contained, styled HTML table (URLs become clickable links)."""
        if not records:
            return None
        df = self._flatten(records).fillna("")
        esc = html.escape

        def cell(value: Any) -> str:
            text = str(value)
            if text.startswith(("http://", "https://")):
                return f'<a href="{esc(text)}" target="_blank" rel="noopener">link</a>'
            return esc(text)

        head = "".join(f"<th>{esc(str(c))}</th>" for c in df.columns)
        body = "".join(
            "<tr>" + "".join(f"<td>{cell(v)}</td>" for v in row) + "</tr>"
            for row in df.itertuples(index=False)
        )
        page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{esc(title)}</title>
<style>
 body{{font-family:Segoe UI,Arial,sans-serif;margin:2rem;color:#222}}
 h1{{color:#1F4E78}} .meta{{color:#666;margin-bottom:1rem}}
 table{{border-collapse:collapse;width:100%;font-size:14px}}
 th{{background:#1F4E78;color:#fff;text-align:left;padding:8px;position:sticky;top:0}}
 td{{padding:6px 8px;border-bottom:1px solid #ddd;vertical-align:top}}
 tr:nth-child(even){{background:#f5f8fb}} a{{color:#1F4E78}}
</style></head><body>
<h1>{esc(title)}</h1>
<div class="meta">{len(df)} records &middot; generated {datetime.now():%Y-%m-%d %H:%M:%S}</div>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
</body></html>"""
        path = self._path(name, "html")
        path.write_text(page, encoding="utf-8")
        self.logger.info("Exported %d records to %s", len(records), path)
        return path
