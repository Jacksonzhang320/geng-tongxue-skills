#!/usr/bin/env python
"""Rank context-aware leads ahead of raw statistical hits."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SEVERITY_BONUS = {"High": 30, "Medium": 10, "Low": 0}
CONFIDENCE_BONUS = {"raw_table": 12, "pdf_extracted": 6, "estimated": -10, "low_confidence": -15}
TYPE_BONUS = {"experimental_measurement": 25, "numeric_unknown": -5}
TYPE_PENALTY = {
    "genomic_or_identifier": -80,
    "derived_stat_or_annotation": -60,
    "design_or_sample_axis": -70,
    "large_structured_table": -55,
    "too_few_numeric_values": -40,
}


def load_json(path: str | None, default: dict) -> dict:
    if not path:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def class_lookup(classes: dict) -> dict[tuple[str, str, str], dict]:
    lookup = {}
    for item in classes.get("column_classes", []):
        key = (item.get("source_path"), item.get("table_name"), item.get("column"))
        lookup[key] = item
    return lookup


def raw_rank_score(finding: dict, cls: dict | None) -> float:
    score = float(finding.get("score", 0))
    score += SEVERITY_BONUS.get(finding.get("severity"), 0)
    score += CONFIDENCE_BONUS.get(finding.get("source_confidence"), 0)
    if cls:
        col_type = cls.get("column_type")
        score += TYPE_BONUS.get(col_type, 0)
        score += TYPE_PENALTY.get(col_type, 0)
        if finding.get("method") not in cls.get("eligible_methods", []) and col_type != "experimental_measurement":
            score -= 30
    return score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--classes")
    parser.add_argument("--context-leads")
    args = parser.parse_args()

    data = load_json(args.findings, {})
    classes = load_json(args.classes, {})
    context = load_json(args.context_leads, {})
    lookup = class_lookup(classes)

    seen = set()
    raw_ranked = []
    for item in data.get("findings", []):
        key = (item.get("source_path"), item.get("table_name"), item.get("column"), item.get("method"), item.get("summary"))
        if key in seen:
            continue
        seen.add(key)
        item = dict(item)
        cls = lookup.get((item.get("source_path"), item.get("table_name"), item.get("column")))
        if cls:
            item["column_type"] = cls.get("column_type")
            item["eligibility_reason"] = cls.get("eligibility_reason")
            item["figure_id"] = cls.get("figure_id")
            item["panels"] = cls.get("panels")
            item["homepage_eligible"] = cls.get("homepage_eligible")
        item["rank_score"] = round(raw_rank_score(item, cls), 3)
        raw_ranked.append(item)
    raw_ranked.sort(key=lambda x: (x.get("rank_score", 0), x.get("n", 0)), reverse=True)
    for i, item in enumerate(raw_ranked, start=1):
        item["rank"] = i

    context_leads = context.get("context_leads", [])
    context_leads = sorted(context_leads, key=lambda x: x.get("context_score", 0), reverse=True)
    for i, item in enumerate(context_leads, start=1):
        item["context_rank"] = i

    result = {
        "context_lead_count": len(context_leads),
        "raw_finding_count": len(raw_ranked),
        "source_raw_finding_count": data.get("finding_count", len(raw_ranked)),
        "context_leads": context_leads,
        "ranked_findings": raw_ranked,
        "notes": [
            "Context-aware leads are the primary triage output.",
            "Raw statistical hits are an appendix and must be interpreted through column type and article context.",
        ],
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(context_leads)} context leads and {len(raw_ranked)} raw findings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
