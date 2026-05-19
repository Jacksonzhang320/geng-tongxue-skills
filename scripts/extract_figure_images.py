#!/usr/bin/env python
"""Extract auditable figure-image inputs from inventory records.

The script is intentionally conservative: it renders PDF pages and registers
standalone image files, but it does not overwrite existing rendered images.
Those rendered page images are cheap checkpoints for later panel segmentation.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def load_inventory(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("files", []))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_stem(text: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text)[:160]


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None


def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: int, max_pages: int | None) -> list[dict[str, Any]]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - depends on runtime
        raise SystemExit("PyMuPDF/fitz is required for PDF page rendering.") from exc

    rows: list[dict[str, Any]] = []
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    page_count = len(doc) if max_pages is None else min(len(doc), max_pages)
    stem = safe_stem(pdf_path.stem)
    page_dir = out_dir / "pages" / stem
    page_dir.mkdir(parents=True, exist_ok=True)
    for page_index in range(page_count):
        page_no = page_index + 1
        out_path = page_dir / f"page_{page_no:04d}.png"
        if not out_path.exists():
            pix = doc.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(out_path))
        size = image_size(out_path)
        rows.append(
            {
                "image_id": f"pdfpage:{safe_stem(str(pdf_path))}:{page_no}",
                "kind": "pdf_page",
                "source_path": str(pdf_path),
                "image_path": str(out_path),
                "page": page_no,
                "dpi": dpi,
                "width": size[0] if size else None,
                "height": size[1] if size else None,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    doc.close()
    return rows


def standalone_image_record(path: Path) -> dict[str, Any]:
    size = image_size(path)
    return {
        "image_id": f"image:{safe_stem(str(path))}",
        "kind": "standalone_image",
        "source_path": str(path),
        "image_path": str(path),
        "page": None,
        "dpi": None,
        "width": size[0] if size else None,
        "height": size[1] if size else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, help="inventory.json from inventory_inputs.py")
    parser.add_argument("--out", required=True, help="Output image_inventory.jsonl")
    parser.add_argument("--work-dir", help="Directory for rendered PDF page checkpoints")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args()

    inventory_path = Path(args.inventory).resolve()
    out_path = Path(args.out).resolve()
    work_dir = Path(args.work_dir).resolve() if args.work_dir else out_path.parent

    rows: list[dict[str, Any]] = []
    for record in load_inventory(inventory_path):
        kind = record.get("kind")
        path = Path(record.get("path", "")).resolve()
        if not path.exists():
            continue
        if kind == "pdf":
            rows.extend(render_pdf_pages(path, work_dir, args.dpi, args.max_pages))
        elif kind == "image" or path.suffix.lower() in IMAGE_EXTS:
            rows.append(standalone_image_record(path))

    write_jsonl(out_path, rows)
    print(f"Wrote {len(rows)} image records to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
