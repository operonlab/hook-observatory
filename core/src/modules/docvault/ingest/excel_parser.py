"""ExcelParserOp — extract sheets + markdown tables from .xlsx / .xls files.

蠶食自 ConardLi/garden-skills kb-retriever (references/excel_reading.md + excel_analysis.md):
- Sheet 探索 (pd.ExcelFile.sheet_names) before loading data
- nrows / usecols 限制 read 範圍避免巨檔 OOM
- Markdown table 輸出 (per-sheet section)

Operator protocol:
  input_keys: ("raw_file", "sheet_filter", "max_rows_per_sheet")
  output_keys: ("raw_content", "metadata")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Heuristic caps — tune based on memvault enrichment latency
DEFAULT_MAX_ROWS_PER_SHEET = 1000  # full read cap
PREVIEW_ROWS = 5  # for "discover schema" pass


def _df_to_markdown(df, sheet_name: str, truncated: bool) -> str:
    """Render a pandas DataFrame as a markdown table section."""
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = []
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            val = row[c]
            # Escape pipes and newlines for markdown safety
            s = str(val).replace("|", "\\|").replace("\n", " ")
            cells.append(s)
        rows.append("| " + " | ".join(cells) + " |")

    trunc_note = f"\n\n_(showing first {len(df)} rows; truncated)_" if truncated else ""
    return f"## Sheet: {sheet_name}\n\n{header}\n{sep}\n" + "\n".join(rows) + trunc_note


def parse_excel(
    file_path: str,
    sheet_filter: list[str] | None = None,
    max_rows_per_sheet: int = DEFAULT_MAX_ROWS_PER_SHEET,
    usecols: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Parse .xlsx / .xls into markdown sections (one per sheet) + metadata.

    Args:
        file_path: Path to Excel file.
        sheet_filter: If set, only include these sheet names (case-sensitive).
        max_rows_per_sheet: Cap rows read per sheet (avoid OOM on large files).
        usecols: If set, only read these column names.

    Returns:
        (content_markdown, metadata_dict)
    """
    import pandas as pd

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {file_path}")

    metadata: dict[str, Any] = {
        "source_type": "excel",
        "title": path.stem,
        "sheets": [],
    }

    # ── Pre-flight: discover sheet names without loading data ──
    excel_file = pd.ExcelFile(file_path)
    all_sheets = excel_file.sheet_names
    metadata["all_sheet_names"] = all_sheets

    target_sheets = (
        [s for s in all_sheets if s in sheet_filter]
        if sheet_filter
        else all_sheets
    )
    if sheet_filter and not target_sheets:
        logger.warning(
            "ExcelParserOp: sheet_filter %s matched none of %s",
            sheet_filter, all_sheets,
        )

    # ── Per-sheet read with bounded rows ──
    sections: list[str] = []
    for sheet_name in target_sheets:
        read_kwargs: dict[str, Any] = {
            "sheet_name": sheet_name,
            "nrows": max_rows_per_sheet,
        }
        if usecols:
            read_kwargs["usecols"] = usecols
        try:
            df = pd.read_excel(excel_file, **read_kwargs)
        except ValueError as e:
            # usecols mismatch is the most common cause
            logger.warning(
                "ExcelParserOp: failed to read sheet '%s' with usecols=%s: %s",
                sheet_name, usecols, e,
            )
            df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=max_rows_per_sheet)

        # Truncation detection: re-read just row count to compare
        full_count_df = pd.read_excel(
            excel_file, sheet_name=sheet_name, usecols=[df.columns[0]] if len(df.columns) else None,
        )
        full_row_count = len(full_count_df)
        truncated = full_row_count > len(df)

        metadata["sheets"].append({
            "name": sheet_name,
            "rows_loaded": len(df),
            "rows_total": full_row_count,
            "columns": list(df.columns),
            "truncated": truncated,
        })

        sections.append(_df_to_markdown(df, sheet_name, truncated))

    content = "\n\n".join(sections) if sections else "_(no sheets loaded)_"
    metadata["sheets_loaded"] = len(sections)
    return content, metadata


class ExcelParserOp:
    """Parse Excel files into markdown sections + metadata.

    Supports .xlsx, .xls via pandas + openpyxl.

    Operator protocol:
      input_keys: ("raw_file", "sheet_filter", "max_rows_per_sheet", "usecols")
      output_keys: ("raw_content", "metadata")
    """

    @property
    def name(self) -> str:
        return "excel_parser"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("raw_file", "sheet_filter", "max_rows_per_sheet", "usecols")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("raw_content", "metadata")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raw_file: str = ctx.get("raw_file", "")

        if not raw_file:
            ctx["raw_content"] = ""
            ctx["metadata"] = {}
            return ctx

        content, metadata = parse_excel(
            raw_file,
            sheet_filter=ctx.get("sheet_filter"),
            max_rows_per_sheet=ctx.get("max_rows_per_sheet", DEFAULT_MAX_ROWS_PER_SHEET),
            usecols=ctx.get("usecols"),
        )

        ctx["raw_content"] = content
        ctx["metadata"] = metadata

        logger.info(
            "ExcelParserOp: %s → %d sheets, %d chars",
            raw_file, metadata.get("sheets_loaded", 0), len(content),
        )
        return ctx
