#!/usr/bin/env python
"""Audit panel images for reuse, transformed reuse, and local clone leads."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def imread_gray(path: str) -> np.ndarray | None:
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        return None
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    return image


def resize_gray(gray: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA)


def dhash(gray: np.ndarray, size: int = 8) -> int:
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def phash(gray: np.ndarray, size: int = 32, low: int = 8) -> int:
    small = cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)
    block = dct[:low, :low].copy()
    med = np.median(block[1:, 1:])
    bits = block > med
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def edge_hist(gray: np.ndarray) -> np.ndarray:
    small = cv2.resize(gray, (160, 160), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(small, 60, 160)
    hist_x = edges.sum(axis=0).astype(np.float32)
    hist_y = edges.sum(axis=1).astype(np.float32)
    vec = np.concatenate([hist_x, hist_y])
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    return float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-9))


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    a -= float(a.mean())
    b -= float(b.mean())
    return float((a * b).sum() / max(math.sqrt(float((a * a).sum() * (b * b).sum())), 1e-9))


def image_ssim(a: np.ndarray, b: np.ndarray) -> float:
    try:
        return float(ssim(a, b, data_range=255))
    except Exception:
        return 0.0


def feature_detector():
    if hasattr(cv2, "SIFT_create"):
        return cv2.SIFT_create(nfeatures=1200), cv2.NORM_L2, "sift"
    if hasattr(cv2, "AKAZE_create"):
        return cv2.AKAZE_create(), cv2.NORM_HAMMING, "akaze"
    return cv2.ORB_create(nfeatures=1500), cv2.NORM_HAMMING, "orb"


def keypoints_and_desc(gray: np.ndarray):
    detector, _, name = feature_detector()
    kp, desc = detector.detectAndCompute(gray, None)
    return kp or [], desc, name


def match_features(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    kpa, da, detector_name = keypoints_and_desc(a)
    kpb, db, _ = keypoints_and_desc(b)
    if da is None or db is None or len(kpa) < 6 or len(kpb) < 6:
        return {
            "detector": detector_name,
            "keypoint_matches": 0,
            "ransac_inliers": 0,
            "inlier_ratio": 0.0,
            "transform": "none",
            "matrix": None,
        }
    _, norm_type, _ = feature_detector()
    matcher = cv2.BFMatcher(norm_type)
    raw = matcher.knnMatch(da, db, k=2)
    good = []
    for pair in raw:
        if len(pair) != 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:
            good.append(m)
    if len(good) < 6:
        return {
            "detector": detector_name,
            "keypoint_matches": len(good),
            "ransac_inliers": 0,
            "inlier_ratio": 0.0,
            "transform": "none",
            "matrix": None,
        }
    pts_a = np.float32([kpa[m.queryIdx].pt for m in good])
    pts_b = np.float32([kpb[m.trainIdx].pt for m in good])
    matrix, inlier_mask = cv2.estimateAffinePartial2D(pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    if matrix is None or inlier_mask is None:
        return {
            "detector": detector_name,
            "keypoint_matches": len(good),
            "ransac_inliers": 0,
            "inlier_ratio": 0.0,
            "transform": "none",
            "matrix": None,
        }
    inliers = int(inlier_mask.ravel().sum())
    ratio = inliers / max(len(good), 1)
    scale_x = math.sqrt(float(matrix[0, 0] ** 2 + matrix[0, 1] ** 2))
    scale_y = math.sqrt(float(matrix[1, 0] ** 2 + matrix[1, 1] ** 2))
    det = float(np.linalg.det(matrix[:, :2]))
    transform = "affine"
    if det < 0:
        transform = "flip_affine"
    elif abs(scale_x - 1.0) > 0.08 or abs(scale_y - 1.0) > 0.08:
        transform = "scale_affine"
    angle = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
    if abs(angle) > 8 and transform == "affine":
        transform = "rotate_affine"
    return {
        "detector": detector_name,
        "keypoint_matches": len(good),
        "ransac_inliers": inliers,
        "inlier_ratio": round(ratio, 4),
        "transform": transform,
        "matrix": [[float(x) for x in row] for row in matrix.tolist()],
        "rotation_degrees": round(angle, 2),
        "scale_x": round(scale_x, 3),
        "scale_y": round(scale_y, 3),
    }


def template_reuse(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    if a.shape[0] * a.shape[1] > b.shape[0] * b.shape[1]:
        small, large, small_name = b, a, "b_in_a"
    else:
        small, large, small_name = a, b, "a_in_b"
    if small.shape[0] < 40 or small.shape[1] < 40:
        return {"template_ncc": 0.0, "template_direction": small_name, "template_bbox": None}
    best = {"template_ncc": -1.0, "template_direction": small_name, "template_bbox": None, "template_scale": 1.0}
    for scale in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6]:
        tmpl = cv2.resize(small, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if tmpl.shape[0] >= large.shape[0] or tmpl.shape[1] >= large.shape[1]:
            continue
        if tmpl.shape[0] < 32 or tmpl.shape[1] < 32:
            continue
        result = cv2.matchTemplate(large, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best["template_ncc"]:
            x, y = max_loc
            best = {
                "template_ncc": round(float(max_val), 4),
                "template_direction": small_name,
                "template_bbox": [int(x), int(y), int(x + tmpl.shape[1]), int(y + tmpl.shape[0])],
                "template_scale": scale,
            }
    if best["template_ncc"] < 0:
        best["template_ncc"] = 0.0
    return best


def pair_metrics(pa: dict[str, Any], pb: dict[str, Any], ga: np.ndarray, gb: np.ndarray) -> dict[str, Any]:
    area_a = ga.shape[0] * ga.shape[1]
    area_b = gb.shape[0] * gb.shape[1]
    same_size_a = resize_gray(ga, (256, 256))
    same_size_b = resize_gray(gb, (256, 256))
    best_whole = {"ncc": ncc(same_size_a, same_size_b), "ssim": image_ssim(same_size_a, same_size_b), "orientation": "normal"}
    for orientation, img in [
        ("flip_horizontal", cv2.flip(same_size_b, 1)),
        ("flip_vertical", cv2.flip(same_size_b, 0)),
        ("flip_both", cv2.flip(same_size_b, -1)),
    ]:
        val = ncc(same_size_a, img)
        if val > best_whole["ncc"]:
            best_whole = {"ncc": val, "ssim": image_ssim(same_size_a, img), "orientation": orientation}
    feat = match_features(ga, gb)
    tmpl = template_reuse(ga, gb)
    overlap_ratio = min(area_a, area_b) / max(area_a, area_b)
    score = 0.0
    match_type = "weak_visual_similarity"
    transform = best_whole["orientation"]
    if best_whole["ncc"] >= 0.93 and best_whole["ssim"] >= 0.82:
        match_type = "whole_panel_reuse"
        score = 92 + 6 * min(best_whole["ncc"], 1.0)
    if tmpl["template_ncc"] >= 0.86 and overlap_ratio < 0.9:
        match_type = "cropped_reuse"
        score = max(score, 78 + 18 * tmpl["template_ncc"])
        transform = f"template_{tmpl['template_direction']}"
    if feat["ransac_inliers"] >= 18 and feat["inlier_ratio"] >= 0.35:
        match_type = "transformed_reuse" if match_type != "cropped_reuse" else match_type
        score = max(score, 74 + min(feat["ransac_inliers"], 80) * 0.25 + feat["inlier_ratio"] * 12)
        transform = feat["transform"]
    return {
        "source_a": pa.get("source_path"),
        "source_b": pb.get("source_path"),
        "page_a": pa.get("page"),
        "page_b": pb.get("page"),
        "figure_id_a": pa.get("figure_id", ""),
        "figure_id_b": pb.get("figure_id", ""),
        "panel_id_a": pa.get("panel_id"),
        "panel_id_b": pb.get("panel_id"),
        "panel_path_a": pa.get("panel_path"),
        "panel_path_b": pb.get("panel_path"),
        "match_type": match_type,
        "transform": transform,
        "score": round(float(min(score, 100.0)), 2),
        "keypoint_matches": feat["keypoint_matches"],
        "ransac_inliers": feat["ransac_inliers"],
        "inlier_ratio": feat["inlier_ratio"],
        "overlap_ratio": round(float(overlap_ratio), 4),
        "ssim": round(float(best_whole["ssim"]), 4),
        "ncc": round(float(best_whole["ncc"]), 4),
        "template_ncc": tmpl["template_ncc"],
        "template_bbox": tmpl["template_bbox"],
        "template_direction": tmpl["template_direction"],
        "details": {"feature": feat, "template": tmpl, "whole_orientation": best_whole["orientation"]},
    }


def local_clone(gray: np.ndarray, patch: int = 64, stride: int = 48) -> dict[str, Any] | None:
    if gray.shape[0] < patch * 2 or gray.shape[1] < patch * 2:
        return None
    features = []
    boxes = []
    for y in range(0, gray.shape[0] - patch + 1, stride):
        for x in range(0, gray.shape[1] - patch + 1, stride):
            block = gray[y : y + patch, x : x + patch]
            if float(block.std()) < 8:
                continue
            small = cv2.resize(block, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
            small -= float(small.mean())
            norm = np.linalg.norm(small)
            if norm == 0:
                continue
            features.append((small / norm).ravel())
            boxes.append((x, y, x + patch, y + patch))
    best = None
    for i in range(len(features)):
        for j in range(i + 1, len(features)):
            a = boxes[i]
            b = boxes[j]
            if max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1])) > patch * patch * 0.1:
                continue
            c = float(np.dot(features[i], features[j]))
            if c > 0.96 and (best is None or c > best["patch_similarity"]):
                best = {"patch_similarity": round(c, 4), "patch_boxes": [list(a), list(b)]}
    return best


def load_panels(panel_manifest: Path, max_panels: int | None) -> list[dict[str, Any]]:
    panels = read_jsonl(panel_manifest)
    if max_panels is not None:
        panels = panels[:max_panels]
    loaded = []
    for panel in panels:
        gray = imread_gray(panel.get("panel_path", ""))
        if gray is None or gray.shape[0] < 48 or gray.shape[1] < 48:
            continue
        panel = dict(panel)
        panel["_gray"] = gray
        panel["_dhash"] = dhash(gray)
        panel["_phash"] = phash(gray)
        panel["_edge_hist"] = edge_hist(gray)
        loaded.append(panel)
    return loaded


def candidate_pairs(panels: list[dict[str, Any]], max_pairs: int | None) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    candidates = []
    exhaustive = len(panels) <= 80
    for pa, pb in combinations(panels, 2):
        if pa.get("panel_path") == pb.get("panel_path"):
            continue
        ph = hamming(pa["_phash"], pb["_phash"])
        dh = hamming(pa["_dhash"], pb["_dhash"])
        eh = corr(pa["_edge_hist"], pb["_edge_hist"])
        area_ratio = min(pa["width"] * pa["height"], pb["width"] * pb["height"]) / max(pa["width"] * pa["height"], pb["width"] * pb["height"])
        recall_score = (64 - min(ph, 64)) + 0.75 * (64 - min(dh, 64)) + 40 * eh + 12 * area_ratio
        if exhaustive or ph <= 18 or dh <= 18 or eh >= 0.55 or area_ratio < 0.65:
            candidates.append((pa, pb, {"phash_distance": ph, "dhash_distance": dh, "edge_hist_corr": round(eh, 4), "area_ratio": round(area_ratio, 4), "recall_score": round(recall_score, 3)}))
    candidates.sort(key=lambda item: item[2]["recall_score"], reverse=True)
    return candidates[:max_pairs] if max_pairs else candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panels", required=True, help="panel_manifest.jsonl")
    parser.add_argument("--out", required=True, help="Output image_findings_raw.json")
    parser.add_argument("--candidates-out", help="Optional image_candidates.jsonl")
    parser.add_argument("--max-panels", type=int)
    parser.add_argument("--max-pairs", type=int, default=5000)
    parser.add_argument("--min-score", type=float, default=60.0)
    parser.add_argument("--local-clone", action="store_true")
    args = parser.parse_args()

    panels = load_panels(Path(args.panels).resolve(), args.max_panels)
    candidates = candidate_pairs(panels, args.max_pairs)
    candidate_rows = []
    findings = []
    for idx, (pa, pb, cand) in enumerate(candidates, start=1):
        candidate_rows.append({**cand, "panel_id_a": pa["panel_id"], "panel_id_b": pb["panel_id"], "panel_path_a": pa["panel_path"], "panel_path_b": pb["panel_path"]})
        metrics = pair_metrics(pa, pb, pa["_gray"], pb["_gray"])
        metrics.update(cand)
        if metrics["score"] >= args.min_score:
            metrics["finding_id"] = f"image-raw-{len(findings) + 1:05d}"
            metrics["method"] = "image_reuse_screen"
            metrics["generated_at"] = datetime.now(timezone.utc).isoformat()
            findings.append(metrics)

    if args.local_clone:
        for panel in panels:
            clone = local_clone(panel["_gray"])
            if clone:
                findings.append(
                    {
                        "finding_id": f"image-raw-{len(findings) + 1:05d}",
                        "method": "local_clone_screen",
                        "source_a": panel.get("source_path"),
                        "source_b": panel.get("source_path"),
                        "page_a": panel.get("page"),
                        "page_b": panel.get("page"),
                        "figure_id_a": panel.get("figure_id", ""),
                        "figure_id_b": panel.get("figure_id", ""),
                        "panel_id_a": panel.get("panel_id"),
                        "panel_id_b": panel.get("panel_id"),
                        "panel_path_a": panel.get("panel_path"),
                        "panel_path_b": panel.get("panel_path"),
                        "match_type": "local_clone",
                        "transform": "within_panel_patch_match",
                        "score": round(70 + 25 * clone["patch_similarity"], 2),
                        "keypoint_matches": 0,
                        "ransac_inliers": 0,
                        "inlier_ratio": 0.0,
                        "overlap_ratio": 0.0,
                        "ssim": clone["patch_similarity"],
                        "ncc": clone["patch_similarity"],
                        "template_ncc": 0.0,
                        "details": clone,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

    findings.sort(key=lambda f: float(f.get("score", 0)), reverse=True)
    out = {
        "assessment_summary": {
            "panel_count": len(panels),
            "candidate_pair_count": len(candidates),
            "raw_image_finding_count": len(findings),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "image_findings": findings,
    }
    write_json(Path(args.out).resolve(), out)
    if args.candidates_out:
        write_jsonl(Path(args.candidates_out).resolve(), candidate_rows)
    print(f"Wrote {len(findings)} raw image findings to {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
