#!/usr/bin/env python
"""Extract numeric-ready tables from mixed paper inputs.

The output is JSONL. Records preserve raw cell strings plus row numbers, cell
addresses, detected header rows, and compact column context so later audit
stages can distinguish measurement values from coordinates, IDs, and design
axes.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable


HEADER_HINTS = {
    "seqnames",
    "chr",
    "chrom",
    "start",
    "end",
    "width",
    "strand",
    "annotation",
    "gene",
    "protein",
    "pvalue",
    "p value",
    "padj",
    "sample",
    "group",
    "condition",
    "time",
    "day",
    "length",
    "width",
    "volume",
    "weight",
    "mean",
    "sd",
    "sem",
    "n",
    "ratio",
    "intensity",
    "level",
}


def load_inventory(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("files", [])


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return re.sub(r"\s+", " ", text)


def excel_col(index: int) -> str:
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def make_unique_columns(values: list[Any], width: int) -> list[str]:
    columns = []
    seen: dict[str, int] = {}
    for i in range(width):
        base = clean_cell(values[i] if i < len(values) else "") or f"col_{i + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        columns.append(base if count == 0 else f"{base}.{count + 1}")
    return columns


def row_nonempty(row: list[Any]) -> list[str]:
    return [clean_cell(v) for v in row if clean_cell(v)]


def is_numeric_text(text: str) -> bool:
    if not text:
        return False
    try:
        float(text.replace(",", ""))
        return True
    except ValueError:
        return False


def header_score(row: list[Any]) -> float:
    cells = row_nonempty(row)
    if not cells:
        return -10.0
    lower = " ".join(cells).lower()
    text_count = sum(1 for c in cells if not is_numeric_text(c))
    numeric_count = sum(1 for c in cells if is_numeric_text(c))
    hint_count = sum(1 for hint in HEADER_HINTS if re.search(rf"\b{re.escape(hint)}\b", lower))
    score = text_count * 2 + hint_count * 5 - numeric_count * 1.5
    if len(cells) >= 3:
        score += 3
    if len(cells) == 1 and len(cells[0]) > 40:
        score -= 6
    return score


def detect_header_row(rows: list[list[Any]]) -> int:
    scan = min(len(rows), 20)
    best_i = 0
    best_score = -999.0
    for i in range(scan):
        score = header_score(rows[i])
        if i + 1 < len(rows):
            next_cells = row_nonempty(rows[i + 1])
            numeric_next = sum(1 for c in next_cells if is_numeric_text(c))
            if next_cells and numeric_next >= max(1, len(next_cells) // 3):
                score += 3
        if score > best_score:
            best_score = score
            best_i = i
    return best_i


def forward_fill_labels(values: list[str]) -> list[str]:
    out = []
    last = ""
    for value in values:
        if value:
            last = value
        out.append(last)
    return out


def build_column_contexts(rows: list[list[Any]], header_i: int, width: int) -> list[str]:
    context_rows = []
    for i in range(max(0, header_i - 3), header_i):
        labels = [clean_cell(rows[i][j] if j < len(rows[i]) else "") for j in range(width)]
        context_rows.append(forward_fill_labels(labels))
    contexts = []
    for col_i in range(width):
        parts = []
        for row in context_rows:
            value = row[col_i] if col_i < len(row) else ""
            if value and value not in parts:
                parts.append(value)
        contexts.append(" | ".join(parts))
    return contexts


def table_record(
    source: Path,
    source_kind: str,
    table_name: str,
    columns: list[str],
    rows: list[list[Any]],
    confidence: str,
    row_numbers: list[int] | None = None,
    column_contexts: list[str] | None = None,
    header_row_index: int | None = None,
) -> dict[str, Any]:
    width = len(columns)
    row_numbers = row_numbers or list(range(1, len(rows) + 1))
    cell_addresses = [[f"{excel_col(i)}{row_no}" for i in range(width)] for row_no in row_numbers]
    return {
        "source_path": str(source),
        "source_kind": source_kind,
        "source_confidence": confidence,
        "table_name": table_name,
        "header_row_index": header_row_index,
        "columns": [str(c) for c in columns],
        "column_contexts": column_contexts or ["" for _ in columns],
        "row_numbers": row_numbers,
        "cell_addresses": cell_addresses,
        "rows": [[clean_cell(v) for v in row[:width]] + [""] * max(0, width - len(row)) for row in rows],
    }


def read_delimited(path: Path, delimiter: str) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=delimiter))
    if not rows:
        return []
    width = max(len(r) for r in rows)
    header_i = detect_header_row(rows)
    columns = make_unique_columns(rows[header_i], width)
    data = rows[header_i + 1 :]
    row_numbers = list(range(header_i + 2, header_i + 2 + len(data)))
    contexts = build_column_contexts(rows, header_i, width)
    return [table_record(path, "table", path.name, columns, data, "raw_table", row_numbers, contexts, header_i + 1)]


def read_excel(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import pandas as pd
    except Exception as exc:
        return [error_record(path, "xlsx dependency missing", exc)]
    out = []
    sheets = pd.read_excel(path, sheet_name=None, dtype=object, header=None)
    for name, df in sheets.items():
        df = df.fillna("")
        rows = df.values.tolist()
        if not rows:
            continue
        width = max(len(r) for r in rows)
        header_i = detect_header_row(rows)
        columns = make_unique_columns(rows[header_i], width)
        data = rows[header_i + 1 :]
        row_numbers = list(range(header_i + 2, header_i + 2 + len(data)))
        contexts = build_column_contexts(rows, header_i, width)
        out.append(table_record(path, "table", str(name), columns, data, "raw_table", row_numbers, contexts, header_i + 1))
    return out


def read_json(path: Path) -> Iterable[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list) and data and isinstance(data[0], dict):
        columns = sorted({str(k) for row in data for k in row.keys()})
        rows = [[row.get(c, "") for c in columns] for row in data]
        return [table_record(path, "array", path.name, columns, rows, "raw_table")]
    if isinstance(data, list) and data and isinstance(data[0], list):
        width = max(len(r) for r in data)
        return [table_record(path, "array", path.name, [f"col_{i+1}" for i in range(width)], data, "raw_table")]
    if isinstance(data, dict):
        columns = [str(k) for k, value in data.items() if isinstance(value, list)]
        if columns:
            max_len = max(len(data[c]) for c in columns)
            rows = [[data[c][i] if i < len(data[c]) else "" for c in columns] for i in range(max_len)]
            return [table_record(path, "array", path.name, columns, rows, "raw_table")]
    return [meta_record(path, "json_not_tabular", "JSON did not contain a simple tabular/list structure.")]


def read_numpy(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import numpy as np
    except Exception as exc:
        return [error_record(path, "numpy dependency missing", exc)]
    arr = np.load(path, allow_pickle=False)
    out = []
    if hasattr(arr, "files"):
        for key in arr.files:
            out.extend(array_to_records(path, key, arr[key]))
    else:
        out.extend(array_to_records(path, path.name, arr))
    return out


def array_to_records(path: Path, name: str, arr: Any) -> list[dict[str, Any]]:
    try:
        import numpy as np
    except Exception:
        np = None
    if np is not None:
        arr = np.asarray(arr)
    if getattr(arr, "ndim", 0) == 1:
        return [table_record(path, "array", name, ["value"], [[v] for v in arr.tolist()], "raw_table")]
    if getattr(arr, "ndim", 0) == 2:
        return [table_record(path, "array", name, [f"col_{i+1}" for i in range(arr.shape[1])], arr.tolist(), "raw_table")]
    return [meta_record(path, "array_not_2d", f"{name}: skipped array with ndim={getattr(arr, 'ndim', 'unknown')}")]


def read_mat(path: Path) -> Iterable[dict[str, Any]]:
    try:
        from scipy.io import loadmat
    except Exception as exc:
        return [error_record(path, "scipy dependency missing", exc)]
    out = []
    data = loadmat(path)
    for key, value in data.items():
        if not key.startswith("__"):
            out.extend(array_to_records(path, key, value))
    return out


def read_pdf(path: Path) -> Iterable[dict[str, Any]]:
    try:
        import pdfplumber
    except Exception as exc:
        return [error_record(path, "pdfplumber dependency missing", exc)]
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for page_i, page in enumerate(pdf.pages, start=1):
            for table_i, table in enumerate(page.extract_tables() or [], start=1):
                if not table:
                    continue
                width = max(len(r or []) for r in table)
                header_i = detect_header_row(table)
                columns = make_unique_columns(table[header_i], width)
                body = table[header_i + 1 :]
                contexts = build_column_contexts(table, header_i, width)
                out.append(table_record(path, "pdf", f"page_{page_i}_table_{table_i}", columns, body, "pdf_extracted", None, contexts, header_i + 1))
    return out or [meta_record(path, "pdf_no_tables", "No extractable PDF tables found.")]


def read_image_sidecars(path: Path) -> Iterable[dict[str, Any]]:
    sidecars = [path.with_name(f"{path.stem}.points.csv"), path.with_name(f"{path.stem}.points.tsv")]
    records = []
    for sidecar in sidecars:
        if not sidecar.exists():
            continue
        delimiter = "\t" if sidecar.suffix.lower() == ".tsv" else ","
        for record in read_delimited(sidecar, delimiter):
            record["source_path"] = str(path)
            record["source_kind"] = "image"
            record["source_confidence"] = "estimated"
            record["table_name"] = f"{sidecar.name} (chart digitization sidecar)"
            records.append(record)
    if records:
        return records
    return [meta_record(path, "image_not_digitized", "Image/chart data requires a same-folder <image_stem>.points.csv or <image_stem>.points.tsv sidecar; treat image-derived values as low-confidence leads.")]


def meta_record(path: Path, status: str, message: str) -> dict[str, Any]:
    return {"source_path": str(path), "status": status, "message": message, "rows": [], "columns": [], "source_confidence": "metadata_only"}


def error_record(path: Path, status: str, exc: Exception) -> dict[str, Any]:
    return {"source_path": str(path), "status": status, "message": str(exc), "rows": [], "columns": [], "source_confidence": "not_extracted"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for item in load_inventory(Path(args.inventory)):
            path = Path(item["path"])
            ext = path.suffix.lower()
            if ext == ".csv":
                records = read_delimited(path, ",")
            elif ext == ".tsv":
                records = read_delimited(path, "\t")
            elif ext in {".xlsx", ".xls"}:
                records = read_excel(path)
            elif ext == ".json":
                records = read_json(path)
            elif ext in {".npy", ".npz"}:
                records = read_numpy(path)
            elif ext == ".mat":
                records = read_mat(path)
            elif ext == ".pdf":
                records = read_pdf(path)
            elif item.get("kind") == "image":
                records = read_image_sidecars(path)
            else:
                records = []
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    print(f"Wrote {count} table/source records to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
