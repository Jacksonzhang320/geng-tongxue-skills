#!/usr/bin/env python
"""Normalize raw image-reuse hits into reviewable risk tiers."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENIGN_EXPLANATIONS = {
    "whole_panel_reuse": ["shared control image", "journal layout duplication", "public reference image", "export or compression artifact"],
    "cropped_reuse": ["shared control image", "intentional inset or zoom", "common field-of-view subset", "figure assembly reuse"],
    "transformed_reuse": ["intentional rotation or mirror display", "same sample shown as inset", "public reference image"],
    "local_clone": ["repeated texture", "low-complexity background", "compression artifact", "template layout"],
    "blot_lane_similarity": ["expected ladder/control lane", "low-resolution blot export", "lane relabeling in composite figure"],
    "weak_visual_similarity": ["template layout", "common microscopy texture", "low-resolution export"],
}


REVIEW_SUGGESTIONS = {
    "whole_panel_reuse": "Review whether the same panel is intentionally reused as a shared control or duplicated under different labels.",
    "cropped_reuse": "Check whether one panel is a labeled inset/zoom of the other; otherwise review original figure-assembly files.",
    "transformed_reuse": "Check whether rotation, scaling, or flipping is explicitly described; otherwise compare source image records.",
    "local_clone": "Inspect the highlighted within-panel patches and review the original uncompressed image.",
    "blot_lane_similarity": "Compare raw blot/gel scans, lane labels, exposure, and loading-control reuse policy.",
    "weak_visual_similarity": "Treat as a low-confidence visual lead unless independent metadata or source data also disagree.",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def risk_for(item: dict[str, Any]) -> tuple[str, str]:
    score = float(item.get("score") or 0)
    match_type = item.get("match_type", "weak_visual_similarity")
    inliers = int(item.get("ransac_inliers") or 0)
    inlier_ratio = float(item.get("inlier_ratio") or 0)
    ncc = float(item.get("ncc") or 0)
    ssim = float(item.get("ssim") or 0)
    template_ncc = float(item.get("template_ncc") or 0)
    if match_type == "whole_panel_reuse" and ncc >= 0.95 and ssim >= 0.85:
        return "High", "Near-identical whole-panel signal after normalization; benign shared-control explanations still need source-image review."
    if match_type == "cropped_reuse" and template_ncc >= 0.9:
        return "High", "Strong template match indicates one panel may be a crop or rescaled subset of the other."
    if match_type == "transformed_reuse" and inliers >= 30 and inlier_ratio >= 0.45:
        return "High", "Feature geometry supports transformed reuse with many RANSAC inliers."
    if match_type == "local_clone" and score >= 92:
        return "High", "Highly similar non-overlapping patches were found inside one panel."
    if score >= 72 or inliers >= 16 or template_ncc >= 0.82:
        return "Medium", "Image similarity is strong enough for human review, but benign explanations or low image quality may remain."
    return "Low", "Weak or single-method visual similarity; use only as an auxiliary lead."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True, help="image_findings_raw.json")
    parser.add_argument("--out", required=True, help="image_findings_normalized.json")
    parser.add_argument("--min-risk", choices=["Low", "Medium", "High"], default="Low")
    args = parser.parse_args()

    raw = load_json(Path(args.findings).resolve())
    order = {"Low": 1, "Medium": 2, "High": 3}
    normalized = []
    for idx, finding in enumerate(raw.get("image_findings", []), start=1):
        item = dict(finding)
        tier, reason = risk_for(item)
        if order[tier] < order[args.min_risk]:
            continue
        match_type = item.get("match_type", "weak_visual_similarity")
        item["finding_id"] = f"image-{len(normalized) + 1:05d}"
        item["normalized_rank"] = len(normalized) + 1
        item["risk_tier"] = tier
        item["risk_reason"] = reason
        item["benign_explanations_checked"] = BENIGN_EXPLANATIONS.get(match_type, BENIGN_EXPLANATIONS["weak_visual_similarity"])
        item["review_suggestion"] = REVIEW_SUGGESTIONS.get(match_type, REVIEW_SUGGESTIONS["weak_visual_similarity"])
        item.setdefault("evidence_images", [])
        item["generated_at"] = datetime.now(timezone.utc).isoformat()
        normalized.append(item)
    normalized.sort(key=lambda f: (order.get(f.get("risk_tier"), 0), float(f.get("score", 0))), reverse=True)
    for rank, item in enumerate(normalized, start=1):
        item["normalized_rank"] = rank

    counts = Counter(item["risk_tier"] for item in normalized)
    result = {
        "assessment_summary": {
            "highest_observed_tier": "High" if counts.get("High") else "Medium" if counts.get("Medium") else "Low" if counts.get("Low") else "none",
            "counts_by_risk_tier": dict(counts),
            "panel_count": raw.get("assessment_summary", {}).get("panel_count", 0),
            "candidate_pair_count": raw.get("assessment_summary", {}).get("candidate_pair_count", 0),
            "raw_image_finding_count": raw.get("assessment_summary", {}).get("raw_image_finding_count", 0),
            "normalized_image_finding_count": len(normalized),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "image_findings": normalized,
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(normalized)} normalized image findings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
