#!/usr/bin/env python
"""Inventory paper-associated files for data forensics."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


TABLE_EXTS = {".csv", ".tsv", ".xlsx", ".xls"}
ARRAY_EXTS = {".npy", ".npz", ".mat", ".json"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def classify(path: Path) -> str:
    ext = path.suffix.lower()
    lower_name = path.name.lower()
    if lower_name.endswith(".points.csv") or lower_name.endswith(".points.tsv"):
        return "chart_points"
    if ext in TABLE_EXTS:
        return "table"
    if ext in ARRAY_EXTS:
        return "array"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Input directory or file")
    parser.add_argument("--out", required=True, help="Output inventory JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Input path does not exist: {root}")

    paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    records = []
    for path in sorted(paths):
        kind = classify(path)
        if kind == "other":
            continue
        stat = path.stat()
        records.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(root.parent if root.is_file() else root)),
                "kind": kind,
                "extension": path.suffix.lower(),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            }
        )

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "root": str(root),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "files": records,
                "counts": {k: sum(1 for r in records if r["kind"] == k) for k in ["table", "array", "pdf", "image"]},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} records to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
