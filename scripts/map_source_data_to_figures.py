#!/usr/bin/env python
"""Map extracted table records to article figure panels."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def infer_figure(text: str) -> tuple[str, str]:
    text = text.replace("Extended Data", "ED")
    patterns = [
        (r"\bED\s*Fig\.?\s*(\d+)", "extended_data"),
        (r"\bSource Data\s+ED\s*Fig\.?\s*(\d+)", "extended_data"),
        (r"\bFig\.?\s*(\d+)", "main"),
        (r"\bSource Data\s+Fig\.?\s*(\d+)", "main"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return (f"ED Fig.{match.group(1)}" if kind == "extended_data" else f"Fig.{match.group(1)}", kind)
    return "", "unknown"


def infer_panels(text: str) -> list[str]:
    panels = set()
    for match in re.finditer(r"\b(?:Fig|ED Fig)\.?\s*\d+\s*([a-z](?:\s*(?:,|and|&)\s*[a-z])*)", text, re.I):
        chunk = match.group(1)
        panels.update(re.findall(r"[a-z]", chunk.lower()))
    for match in re.finditer(r"\b([a-z])\s*(?:and|&)\s*([a-z])\b", text, re.I):
        panels.update([match.group(1).lower(), match.group(2).lower()])
    return sorted(panels)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", required=True)
    parser.add_argument("--context")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    context = json.loads(Path(args.context).read_text(encoding="utf-8")) if args.context else {"figures": []}
    captions = {fig["figure_id"]: fig for fig in context.get("figures", [])}
    mappings = []
    for idx, table in enumerate(load_jsonl(Path(args.tables))):
        text = f"{Path(table.get('source_path', '')).name} {table.get('table_name', '')}"
        figure_id, figure_type = infer_figure(text)
        panels = infer_panels(text)
        caption = captions.get(figure_id, {})
        mappings.append(
            {
                "table_index": idx,
                "source_path": table.get("source_path"),
                "table_name": table.get("table_name"),
                "figure_id": figure_id,
                "figure_type": figure_type,
                "panels": panels,
                "caption_heading": caption.get("heading", ""),
                "caption": caption.get("caption", ""),
                "mapped": bool(figure_id),
            }
        )
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mappings": mappings, "mapped_count": sum(1 for m in mappings if m["mapped"])}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(mappings)} table mappings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
