#!/usr/bin/env python
"""Score normalized statistical findings against a benchmark oracle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def matches(item: dict, finding: dict) -> bool:
    if item.get("error_type") != finding.get("error_type"):
        return False
    if item.get("source_contains") and item["source_contains"] not in str(finding.get("source_path", "")):
        return False
    if item.get("table_name") and item["table_name"] != finding.get("table_name"):
        return False
    expected_cols = set(item.get("columns", []))
    blob = " ".join([str(finding.get("column", "")), str(finding.get("details", "")), str(finding.get("evidence_examples", ""))])
    return not expected_cols or any(col in blob for col in expected_cols)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True)
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = load(args.findings)
    oracle = load(args.oracle)
    findings = data.get("normalized_findings", [])
    results = []
    for item in oracle.get("oracle_items", []):
        hits = [f for f in findings if matches(item, f) and f.get("disposition") != "not_applicable"]
        exact = [f for f in hits if f.get("disposition") == item.get("expected_disposition")]
        status = "exact" if exact else ("near" if hits else "miss")
        first = (exact or hits or [{}])[0]
        results.append(
            {
                "oracle_id": item.get("id"),
                "error_type": item.get("error_type"),
                "expected_disposition": item.get("expected_disposition"),
                "status": status,
                "first_hit_rank": first.get("normalized_rank"),
                "first_hit_disposition": first.get("disposition"),
                "first_hit_summary": first.get("summary", ""),
            }
        )
    exact_rate = sum(r["status"] == "exact" for r in results) / max(len(results), 1)
    near_rate = sum(r["status"] in {"exact", "near"} for r in results) / max(len(results), 1)
    decoy_failures = [
        f
        for f in findings
        if f.get("disposition") == "high_confidence_fabrication_compatible_anomaly"
        and f.get("column_type") in {"genomic_or_identifier", "derived_stat_or_annotation", "design_or_sample_axis", "large_structured_table"}
    ]
    report = {
        "case_id": oracle.get("case_id"),
        "exact_recovery_rate": exact_rate,
        "exact_or_near_recovery_rate": near_rate,
        "decoy_high_priority_failures": len(decoy_failures),
        "passed": exact_rate >= oracle.get("min_exact_rate", 0.7) and near_rate >= oracle.get("min_near_rate", 0.85) and not decoy_failures,
        "results": results,
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote statistical benchmark score to {out}; passed={report['passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
