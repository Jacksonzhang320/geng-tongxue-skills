#!/usr/bin/env python
"""Render a Chinese Markdown image-chain report with PNG/SVG evidence figures."""
from __future__ import annotations

import argparse
import base64
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


TIER_CN = {"High": "高风险图片复用线索", "Medium": "中风险图片复用线索", "Low": "低风险辅助线索", "none": "未发现保留线索"}
MATCH_CN = {
    "whole_panel_reuse": "整图/整panel高度相似",
    "cropped_reuse": "裁剪或缩放后复用",
    "transformed_reuse": "几何变换后复用",
    "local_clone": "同一panel内局部克隆",
    "blot_lane_similarity": "blot/gel条带相似",
    "weak_visual_similarity": "弱视觉相似",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def imread_rgb(path: str) -> np.ndarray | None:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def fit_image(image: np.ndarray, max_w: int = 520, max_h: int = 420) -> Image.Image:
    pil = Image.fromarray(image)
    pil.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    return pil


def font(size: int = 18) -> ImageFont.ImageFont:
    for name in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf"]:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: tuple[int, int, int] = (0, 0, 0)) -> None:
    draw.text(xy, text, font=font(18), fill=fill)


def write_svg_from_png(svg_path: Path, png_path: Path, width: int, height: int) -> None:
    encoded = base64.b64encode(png_path.read_bytes()).decode("ascii")
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
    svg += f'  <image href="data:image/png;base64,{encoded}" width="{width}" height="{height}"/>\n'
    svg += "</svg>\n"
    svg_path.write_text(svg, encoding="utf-8")


def evidence_canvas(item: dict[str, Any], out_dir: Path) -> list[str]:
    a = imread_rgb(item.get("panel_path_a", ""))
    b = imread_rgb(item.get("panel_path_b", ""))
    if a is None:
        return []
    if b is None:
        b = a.copy()
    pa = fit_image(a)
    pb = fit_image(b)
    pad = 24
    header_h = 96
    footer_h = 110
    w = pa.width + pb.width + pad * 3
    h = max(pa.height, pb.height) + header_h + footer_h
    canvas = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(canvas)
    title = f"{item.get('finding_id')} | {TIER_CN.get(item.get('risk_tier'), item.get('risk_tier'))} | {MATCH_CN.get(item.get('match_type'), item.get('match_type'))}"
    draw_label(draw, (pad, 18), title)
    metrics = f"score={item.get('score')}  NCC={item.get('ncc')}  SSIM={item.get('ssim')}  RANSAC={item.get('ransac_inliers')}/{item.get('keypoint_matches')}  overlap={item.get('overlap_ratio')}"
    draw_label(draw, (pad, 52), metrics, (70, 70, 70))
    y0 = header_h
    canvas.paste(pa, (pad, y0))
    canvas.paste(pb, (pad * 2 + pa.width, y0))
    draw.rectangle((pad, y0, pad + pa.width, y0 + pa.height), outline=(30, 90, 160), width=3)
    draw.rectangle((pad * 2 + pa.width, y0, pad * 2 + pa.width + pb.width, y0 + pb.height), outline=(180, 80, 40), width=3)
    if item.get("template_bbox") and item.get("template_direction") in {"a_in_b", "b_in_a"}:
        target_x = pad * 2 + pa.width if item["template_direction"] == "a_in_b" else pad
        target_img = pb if item["template_direction"] == "a_in_b" else pa
        src_path = item.get("panel_path_b") if item["template_direction"] == "a_in_b" else item.get("panel_path_a")
        src = imread_rgb(src_path or "")
        if src is not None:
            sx = target_img.width / max(src.shape[1], 1)
            sy = target_img.height / max(src.shape[0], 1)
            x0, yb0, x1, yb1 = item["template_bbox"]
            draw.rectangle((target_x + x0 * sx, y0 + yb0 * sy, target_x + x1 * sx, y0 + yb1 * sy), outline=(220, 0, 0), width=4)
    if item.get("match_type") == "local_clone" and item.get("details", {}).get("patch_boxes"):
        sx = pa.width / max(a.shape[1], 1)
        sy = pa.height / max(a.shape[0], 1)
        for box in item["details"]["patch_boxes"]:
            x0, yb0, x1, yb1 = box
            draw.rectangle((pad + x0 * sx, y0 + yb0 * sy, pad + x1 * sx, y0 + yb1 * sy), outline=(220, 0, 0), width=4)
    footer_y = y0 + max(pa.height, pb.height) + 16
    draw_label(draw, (pad, footer_y), f"A: {item.get('panel_id_a')} | page={item.get('page_a')} | {item.get('source_a')}", (40, 40, 40))
    draw_label(draw, (pad, footer_y + 30), f"B: {item.get('panel_id_b')} | page={item.get('page_b')} | {item.get('source_b')}", (40, 40, 40))
    draw_label(draw, (pad, footer_y + 60), f"review: {item.get('review_suggestion', '')}", (40, 40, 40))
    stem = f"{int(item.get('normalized_rank', 0)):03d}_{item.get('finding_id')}_{item.get('match_type')}"
    stem = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    png_path = out_dir / f"{stem}.png"
    svg_path = out_dir / f"{stem}.svg"
    out_dir.mkdir(parents=True, exist_ok=True)
    canvas.save(png_path)
    write_svg_from_png(svg_path, png_path, canvas.width, canvas.height)
    item["evidence_images"] = [str(png_path), str(svg_path)]
    return [str(png_path), str(svg_path)]


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(x).replace("|", "\\|")[:260] for x in row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True, help="image_findings_normalized.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    data = load_json(Path(args.findings).resolve())
    out_dir = Path(args.out_dir).resolve()
    evidence_dir = out_dir / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    findings = data.get("image_findings", [])[: args.top]
    for item in findings:
        evidence_canvas(item, evidence_dir)

    summary = data.get("assessment_summary", {})
    counts = Counter(item.get("risk_tier", "unknown") for item in findings)
    lines = [
        "# 论文图片链路异常探查报告",
        "",
        "本报告只生成可复核的图片链路线索，不证明学术不端。高风险表示图像相似、裁剪、几何变换或局部克隆证据较强，仍需结合原始图像、figure assembly 文件、图注和作者解释复核。",
        "",
        "## 评估摘要",
        "",
        f"- 最高观察等级：{TIER_CN.get(summary.get('highest_observed_tier', 'none'), summary.get('highest_observed_tier', 'none'))} (`{summary.get('highest_observed_tier', 'none')}`)",
        f"- panel 数量：{summary.get('panel_count', 'NA')}",
        f"- 候选 pair 数量：{summary.get('candidate_pair_count', 'NA')}",
        f"- raw 图片命中数量：{summary.get('raw_image_finding_count', 'NA')}",
        f"- 归一化保留线索数量：{summary.get('normalized_image_finding_count', len(findings))}",
        f"- High/Medium/Low：{counts.get('High', 0)}/{counts.get('Medium', 0)}/{counts.get('Low', 0)}",
        "",
        "## 图片链路线索",
        "",
    ]
    if not findings:
        lines.append("未发现达到阈值的图片链路线索。")
        lines.append("")
    for item in findings:
        lines.extend(
            [
                f"### #{item.get('normalized_rank')} {TIER_CN.get(item.get('risk_tier'), item.get('risk_tier'))} | {MATCH_CN.get(item.get('match_type'), item.get('match_type'))}",
                "",
                f"- finding_id：`{item.get('finding_id')}`",
                f"- A：`{item.get('panel_id_a')}` page={item.get('page_a')} source=`{item.get('source_a')}`",
                f"- B：`{item.get('panel_id_b')}` page={item.get('page_b')} source=`{item.get('source_b')}`",
                f"- transform：`{item.get('transform')}`；score={item.get('score')}；NCC={item.get('ncc')}；SSIM={item.get('ssim')}；RANSAC inliers={item.get('ransac_inliers')}/{item.get('keypoint_matches')}",
                f"- 判断理由：{item.get('risk_reason')}",
                f"- 已考虑的良性解释：{'; '.join(item.get('benign_explanations_checked', []))}",
                f"- 人工复核建议：{item.get('review_suggestion')}",
            ]
        )
        images = item.get("evidence_images", [])
        if images:
            lines.append(f"- 证据图：`{images[0]}`；`{images[1] if len(images) > 1 else ''}`")
            lines.append("")
            lines.append(f"![evidence]({images[0]})")
        lines.append("")

    lines.extend(
        [
            "## 方法边界",
            "",
            "- 图片重复检测会受分辨率、压缩、公共对照图、模板版式、重复纹理、低复杂度背景和期刊导出流程影响。",
            "- `whole_panel_reuse`、`cropped_reuse`、`transformed_reuse` 和 `local_clone` 都只是复核优先级线索。",
            "- Western blot/gel 的 lane 复用需要原始整膜、曝光记录和 lane 标注一起复核；当前版本只提供视觉线索框架。",
            "- 图表类图片应优先回到 source data 或图像数字化数据，不把版式相似当作图片复用证据。",
        ]
    )
    report = out_dir / "image_chain_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    refreshed = out_dir / "image_findings_normalized.with_evidence.json"
    refreshed.write_text(json.dumps({**data, "image_findings": findings}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote image-chain report to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
