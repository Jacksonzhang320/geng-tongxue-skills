#!/usr/bin/env python
"""Create conservative panel crops from rendered pages and image files."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_stem(text: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in text)[:150]


def imread_rgb(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def imwrite_rgb(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    ok, data = cv2.imencode(".png", bgr)
    if not ok:
        raise OSError(f"Failed to encode {path}")
    data.tofile(str(path))


def crop_nonwhite_bbox(image: np.ndarray, margin: int = 8) -> tuple[int, int, int, int]:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    mask = gray < 248
    if mask.sum() < 50:
        return 0, 0, image.shape[1], image.shape[0]
    ys, xs = np.where(mask)
    x0 = max(int(xs.min()) - margin, 0)
    y0 = max(int(ys.min()) - margin, 0)
    x1 = min(int(xs.max()) + margin + 1, image.shape[1])
    y1 = min(int(ys.max()) + margin + 1, image.shape[0])
    return x0, y0, x1, y1


def component_boxes(image: np.ndarray, min_area: int, max_panels: int) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    mask = (gray < 245).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    h, w = image.shape[:2]
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = bw * bh
        if area < min_area:
            continue
        if bw < 80 or bh < 80:
            continue
        if bw > 0.96 * w and bh > 0.96 * h:
            continue
        pad = 8
        boxes.append((max(x - pad, 0), max(y - pad, 0), min(x + bw + pad, w), min(y + bh + pad, h)))
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    return boxes[:max_panels]


def is_informative(crop: np.ndarray) -> bool:
    if crop.shape[0] < 64 or crop.shape[1] < 64:
        return False
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    nonwhite = float((gray < 245).mean())
    return nonwhite > 0.03 and float(gray.std()) > 3.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-inventory", required=True)
    parser.add_argument("--out", required=True, help="Output panel_manifest.jsonl")
    parser.add_argument("--work-dir", help="Directory for panel crops")
    parser.add_argument("--split-pages", action="store_true", help="Also save large connected components from PDF pages")
    parser.add_argument("--max-panels-per-image", type=int, default=80)
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    work_dir = Path(args.work_dir).resolve() if args.work_dir else out_path.parent
    panel_dir = work_dir / "panels"
    rows: list[dict[str, Any]] = []

    for image_index, record in enumerate(read_jsonl(Path(args.image_inventory).resolve()), start=1):
        src_path = Path(record["image_path"]).resolve()
        image = imread_rgb(src_path)
        if image is None:
            continue
        boxes = [crop_nonwhite_bbox(image)]
        if args.split_pages and record.get("kind") == "pdf_page":
            min_area = max(12000, int(image.shape[0] * image.shape[1] * 0.015))
            boxes.extend(component_boxes(image, min_area, args.max_panels_per_image))
        seen = set()
        panel_no = 0
        for box in boxes:
            if box in seen:
                continue
            seen.add(box)
            x0, y0, x1, y1 = box
            crop = image[y0:y1, x0:x1]
            if not is_informative(crop):
                continue
            panel_no += 1
            panel_id = f"panel-{image_index:05d}-{panel_no:03d}"
            stem = safe_stem(panel_id + "_" + Path(record.get("source_path", src_path)).stem)
            crop_path = panel_dir / f"{stem}.png"
            if not crop_path.exists():
                imwrite_rgb(crop_path, crop)
            rows.append(
                {
                    "panel_id": panel_id,
                    "image_id": record.get("image_id"),
                    "source_path": record.get("source_path"),
                    "image_path": record.get("image_path"),
                    "panel_path": str(crop_path),
                    "page": record.get("page"),
                    "figure_id": "",
                    "panel_label": "",
                    "bbox_xyxy": [int(x0), int(y0), int(x1), int(y1)],
                    "width": int(crop.shape[1]),
                    "height": int(crop.shape[0]),
                    "kind": record.get("kind"),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

    write_jsonl(out_path, rows)
    print(f"Wrote {len(rows)} panel records to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
