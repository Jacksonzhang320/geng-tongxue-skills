#!/usr/bin/env python
"""Score blind audit leads against known public benchmark oracles."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ORACLES = {
    "hdac6_valine_nature_2024": {
        "article": "Human HDAC6 senses valine abundancy to regulate DNA damage",
        "oracle_items": [
            {"id": "fig_2f", "label": "Fig. 2f", "problem_family": "image_or_label_preparation"},
            {"id": "ed_fig_7k", "label": "Extended Data Fig. 7k", "problem_family": "image_or_label_preparation"},
            {"id": "ed_fig_10e", "label": "Extended Data Fig. 10e", "problem_family": "image_or_label_preparation"},
        ],
        "public_context": "Nature author correction and editor note; use only after blind lead generation.",
    }
}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def parse_label(label: str) -> tuple[str, str, str]:
    kind = "ed" if re.search(r"Extended Data|ED\s*Fig", label, re.I) else "main"
    match = re.search(r"(?:Extended Data Fig\.|ED\s*Fig\.|Fig\.)\s*(\d+)\s*([a-z]?)", label, re.I)
    if not match:
        return kind, "", ""
    return kind, match.group(1), match.group(2).lower()


def lead_figures(lead: dict) -> list[tuple[str, str, str]]:
    blob = json.dumps(lead, ensure_ascii=False)
    out = []
    for match in re.finditer(r"(Extended Data Fig\.|ED\s*Fig\.|Fig\.)\s*(\d+)\s*([a-z]?)", blob, re.I):
        raw = match.group(1)
        kind = "ed" if raw.lower().startswith(("extended", "ed")) else "main"
        out.append((kind, match.group(2), match.group(3).lower()))
    return out


def item_match(item: dict, lead: dict) -> str:
    target_kind, target_num, target_panel = parse_label(item["label"])
    if not target_num:
        return "missed_oracle"
    candidates = lead_figures(lead)
    if any(kind == target_kind and num == target_num and panel == target_panel for kind, num, panel in candidates):
        return "true_positive"
    if any(kind == target_kind and num == target_num for kind, num, _panel in candidates):
        return "near_miss"
    return "missed_oracle"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=sorted(ORACLES))
    parser.add_argument("--leads", required=True, help="context_leads.json or ranked JSON")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    oracle = ORACLES[args.case]
    data = json.loads(Path(args.leads).read_text(encoding="utf-8"))
    leads = data.get("context_leads") or data.get("ranked_findings") or []
    results = []
    for item in oracle["oracle_items"]:
        scored_hits = [(item_match(item, lead), lead) for lead in leads]
        exact_hits = [lead for status, lead in scored_hits if status == "true_positive"]
        near_hits = [lead for status, lead in scored_hits if status == "near_miss"]
        hits = exact_hits or near_hits
        status = "true_positive" if exact_hits else ("near_miss" if near_hits else "missed_oracle")
        results.append(
            {
                "oracle_id": item["id"],
                "label": item["label"],
                "problem_family": item["problem_family"],
                "status": status,
                "first_hit_rank": hits[0].get("context_rank", hits[0].get("rank")) if hits else None,
                "first_hit_summary": hits[0].get("summary") if hits else "",
            }
        )
    score = sum(1 for r in results if r["status"] == "true_positive") / len(results)
    near_score = sum(1 for r in results if r["status"] in {"true_positive", "near_miss"}) / len(results)
    report = {
        "case": args.case,
        "article": oracle["article"],
        "public_context": oracle["public_context"],
        "recovery_rate": score,
        "near_miss_or_better_rate": near_score,
        "results": results,
        "notes": [
            "Use this only after blind lead generation.",
            "Near misses should be reviewed manually when the lead identifies the same problem family but not the exact panel.",
        ],
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote benchmark score {score:.3f} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
