#!/usr/bin/env python
"""Normalize raw statistical hits into reportable fabrication-compatible dispositions."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ERROR_TYPES = {
    "last_digit_distribution": "terminal_digit_heaping",
    "decimal_tail_regularity": "decimal_tail_heaping",
    "duplicate_values": "duplicate_value_cluster",
    "duplicate_rows": "duplicate_row_clone",
    "clone_vector": "clone_vector",
    "arithmetic_or_over_smooth_sequence": "arithmetic_smoothness",
    "summary_math_inconsistency": "summary_math_inconsistency",
    "formula_mismatch": "formula_mismatch",
    "benford_first_digit": "benford_misfit",
}

BENIGN = {
    "terminal_digit_heaping": ["rounding", "instrument precision", "manual thresholding", "bounded/discrete data"],
    "decimal_tail_heaping": ["rounding", "instrument precision", "export formatting", "manual thresholding"],
    "duplicate_value_cluster": ["bounded/discrete data", "rounding", "instrument resolution", "plateau/limit of detection"],
    "duplicate_row_clone": ["template/header duplication", "intentional replicate labels", "merged panel formatting"],
    "clone_vector": ["shared normalization control", "copied design axis", "intentional repeated standard curve"],
    "arithmetic_smoothness": ["fixed design axis", "interpolation", "instrument step size"],
    "summary_math_inconsistency": ["reported SD vs SEM ambiguity", "rounding", "different replicate definition"],
    "formula_mismatch": ["different formula convention", "unit conversion", "rounding"],
    "benford_misfit": ["bounded range", "thresholding", "non-Benford experimental design"],
}


def load_json(path: str | None, default: dict) -> dict:
    if not path:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def text_for_finding(finding: dict, cls: dict | None) -> str:
    parts = [
        finding.get("table_name", ""),
        finding.get("column", ""),
        finding.get("summary", ""),
        (cls or {}).get("column_context", ""),
        (cls or {}).get("eligibility_reason", ""),
    ]
    return re.sub(r"[_\-]+", " ", " ".join(str(p) for p in parts).lower())


def example_values(finding: dict) -> list[str]:
    return [str(ex.get("value", "")).strip().replace(",", "") for ex in finding.get("details", {}).get("evidence_examples", [])]


def examples_are_integer_like(finding: dict) -> bool:
    vals = [v for v in example_values(finding) if v]
    return bool(vals) and all(re.fullmatch(r"[-+]?\d+(?:\.0+)?", v) for v in vals)


def examples_are_plain_integers(finding: dict) -> bool:
    vals = [v for v in example_values(finding) if v]
    return bool(vals) and all(re.fullmatch(r"[-+]?\d+", v) for v in vals)


def integer_decimal_tail_hit(finding: dict) -> bool:
    details = finding.get("details", {})
    tails = details.get("top_tails", {})
    return finding.get("method") == "decimal_tail_regularity" and set(tails) <= {"00"} and examples_are_plain_integers(finding)


def zero_terminal_export_hit(finding: dict, cls: dict | None) -> bool:
    if finding.get("method") != "last_digit_distribution":
        return False
    counts = finding.get("details", {}).get("counts", {})
    n = int(finding.get("n") or 0)
    zero_frac = counts.get("0", 0) / max(n, 1) if counts else 0
    text = text_for_finding(finding, cls)
    export_context = re.search(r"\b(intensity|silac|ms data|mass spec|proteomic|spectrometry)\b", text)
    return zero_frac >= 0.95 and examples_are_integer_like(finding) and bool(export_context)


def discrete_count_hit(finding: dict, cls: dict | None) -> bool:
    text = text_for_finding(finding, cls)
    return bool(re.search(r"\b(count|unique peptides?|razor.*peptides?|ms/ms|sequence coverage|number)\b", text))


def anonymous_column_hit(finding: dict) -> bool:
    return bool(re.fullmatch(r"col_\d+", str(finding.get("column", "")).strip().lower()))


def class_lookup(classes: dict) -> dict[tuple[str, str, str], dict]:
    lookup = {}
    for item in classes.get("column_classes", []):
        lookup[(item.get("source_path"), item.get("table_name"), item.get("column"))] = item
    return lookup


def lookup_class(finding: dict, lookup: dict[tuple[str, str, str], dict]) -> dict | None:
    source = finding.get("source_path")
    table = finding.get("table_name")
    column = finding.get("column")
    cls = lookup.get((source, table, column))
    if cls or finding.get("method") != "clone_vector" or " <> " not in str(column):
        return cls
    parts = [part.strip() for part in str(column).split(" <> ")]
    part_classes = [lookup.get((source, table, part)) for part in parts]
    if part_classes and all(c and c.get("applicability") == "applicable" for c in part_classes):
        merged = dict(part_classes[0])
        merged["column"] = column
        merged["column_type"] = "experimental_measurement"
        merged["applicability"] = "applicable"
        merged["eligibility_reason"] = "Both cloned-vector columns are eligible experimental measurements."
        return merged
    if part_classes and all(c for c in part_classes):
        merged = dict(part_classes[0])
        merged["column"] = column
        merged["column_type"] = "clone_vector_ineligible_components"
        merged["applicability"] = "not_applicable"
        merged["eligibility_reason"] = "Clone-vector components are not both eligible experimental measurements; design axes, IDs, and summary metadata are excluded."
        return merged
    return cls


def disposition_for(finding: dict, cls: dict | None, family_count: int) -> tuple[str, str, str]:
    method = finding.get("method")
    error_type = ERROR_TYPES.get(method, method or "unknown")
    applicability = (cls or {}).get("applicability", "limited")
    column_type = (cls or {}).get("column_type", "unknown")
    n = int(finding.get("n") or 0)
    score = float(finding.get("score") or 0)
    if applicability == "not_applicable" or column_type in {"genomic_or_identifier", "derived_stat_or_annotation", "design_or_sample_axis", "large_structured_table", "too_few_numeric_values", "clone_vector_ineligible_components"}:
        return "not_applicable", error_type, (cls or {}).get("eligibility_reason", "Column type is not eligible for this statistical test.")
    if column_type == "summary_statistic" and method != "summary_math_inconsistency":
        return "not_applicable", error_type, "Summary-statistic field; raw digit, decimal-tail, duplicate, and smoothness screens are not fabrication-compatible evidence."
    if anonymous_column_hit(finding) and method in {"last_digit_distribution", "decimal_tail_regularity", "duplicate_values", "arithmetic_or_over_smooth_sequence"}:
        return "not_applicable", error_type, "Anonymous extracted column (col_N); header/source-data mapping is unresolved, so raw digit or smoothness hits cannot be treated as fabrication-compatible evidence."
    if integer_decimal_tail_hit(finding):
        return "not_applicable", error_type, "Decimal-tail test is not applicable when the observed values are integer-only exports."
    if discrete_count_hit(finding, cls) and method in {"last_digit_distribution", "decimal_tail_regularity", "duplicate_values", "arithmetic_or_over_smooth_sequence"}:
        return "not_applicable", error_type, "Discrete count or peptide-count field; repeated values and tidy digits are expected and not fabrication-compatible evidence by themselves."
    if zero_terminal_export_hit(finding, cls):
        return "not_applicable", error_type, "Terminal-zero heaping in integer/export-quantized values is treated as a precision or export-format artifact, not a fabrication-compatible statistical anomaly."
    if method == "summary_math_inconsistency" and column_type == "summary_statistic" and n >= 1:
        return "high_confidence_fabrication_compatible_anomaly", error_type, "Reported summary statistic is mathematically inconsistent with companion n/SD/SEM fields beyond tolerance."
    if applicability == "applicable" and method in {"clone_vector", "summary_math_inconsistency", "formula_mismatch", "duplicate_rows"} and n >= 5:
        return "high_confidence_fabrication_compatible_anomaly", error_type, "Exact clone/math/formula inconsistency in eligible source data; benign explanations still require source-record review."
    if method == "duplicate_values" and applicability == "applicable":
        return "weak_anomaly", error_type, "Scalar duplicate clusters are a weak lead unless they form row/vector clones or contradict replicate design."
    if applicability == "applicable" and method == "last_digit_distribution" and n >= 50:
        counts = finding.get("details", {}).get("counts", {})
        max_frac = max(counts.values()) / max(n, 1) if counts else 0
        p = finding.get("details", {}).get("p_approx", 1.0)
        top_digit = max(counts, key=counts.get) if counts else ""
        missing_count = len(finding.get("details", {}).get("missing_digits", []))
        if top_digit != "0" and (max_frac >= 0.45 or (p < 1e-8 and max_frac >= 0.35 and missing_count >= 3)):
            return "high_confidence_fabrication_compatible_anomaly", error_type, "Strong terminal-digit heaping in eligible measurement data."
    if applicability == "applicable" and method == "decimal_tail_regularity" and n >= 50:
        tails = finding.get("details", {}).get("top_tails", {})
        max_frac = max(tails.values()) / max(n, 1) if tails else 0
        tidy_frac = finding.get("details", {}).get("tidy_tail_count", 0) / max(n, 1)
        top_tail = max(tails, key=tails.get) if tails else ""
        if top_tail != "00" and (max_frac >= 0.45 or tidy_frac >= 0.65):
            return "high_confidence_fabrication_compatible_anomaly", error_type, "Strong repeated decimal-tail pattern in eligible measurement data."
    if applicability == "applicable" and method == "arithmetic_or_over_smooth_sequence" and n >= 20:
        diff_cv = finding.get("details", {}).get("diff_cv", 1.0)
        step_count = finding.get("details", {}).get("common_step_count", 0)
        if diff_cv < 0.02 or step_count / max(n - 1, 1) >= 0.75:
            return "high_confidence_fabrication_compatible_anomaly", error_type, "Overly regular row-order step pattern in eligible measurement data."
    if family_count >= 2 and n >= 20 and score >= 80 and applicability == "applicable" and method not in {"last_digit_distribution", "decimal_tail_regularity", "duplicate_values"}:
        return "high_confidence_fabrication_compatible_anomaly", error_type, "Multiple independent statistical anomaly families hit the same eligible measurement column."
    if applicability in {"applicable", "limited"}:
        return "weak_anomaly", error_type, "Single-method or limited-context anomaly; plausible rounding/design explanations remain."
    return "not_applicable", error_type, "Insufficient applicability context."


def rank_key(item: dict) -> tuple[int, float, int]:
    disp_order = {"high_confidence_fabrication_compatible_anomaly": 3, "weak_anomaly": 2, "not_applicable": 1}
    return (disp_order.get(item.get("disposition"), 0), float(item.get("rank_score", item.get("score", 0))), int(item.get("n", 0)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", required=True, help="Raw findings JSON or ranked JSON")
    parser.add_argument("--classes", required=True)
    parser.add_argument("--context-leads")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    data = load_json(args.findings, {})
    raw = data.get("findings") or data.get("ranked_findings") or []
    classes = load_json(args.classes, {})
    context = load_json(args.context_leads, {})
    lookup = class_lookup(classes)
    column_class_count = len(classes.get("column_classes", []))

    family_by_col: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for finding in raw:
        key = (finding.get("source_path"), finding.get("table_name"), finding.get("column"))
        family_by_col[key].add(finding.get("method", ""))

    normalized = []
    seen_caps = Counter()
    for idx, finding in enumerate(raw, start=1):
        key = (finding.get("source_path"), finding.get("table_name"), finding.get("column"))
        cls = lookup_class(finding, lookup)
        disposition, error_type, reason = disposition_for(finding, cls, len(family_by_col[key]))
        cap_key = (finding.get("source_path"), finding.get("table_name"), finding.get("column"), error_type, disposition)
        seen_caps[cap_key] += 1
        if seen_caps[cap_key] > 3:
            continue
        item = dict(finding)
        item["finding_id"] = f"stat-{idx:05d}"
        item["error_type"] = error_type
        item["disposition"] = disposition
        item["disposition_reason"] = reason
        item["applicability"] = (cls or {}).get("applicability", "limited")
        item["column_type"] = (cls or {}).get("column_type", item.get("column_type", "unknown"))
        item["eligibility_reason"] = (cls or {}).get("eligibility_reason", item.get("eligibility_reason", ""))
        item["figure_id"] = (cls or {}).get("figure_id", item.get("figure_id", ""))
        item["panels"] = (cls or {}).get("panels", item.get("panels", []))
        item["column_context"] = (cls or {}).get("column_context", "")
        item["evidence_examples"] = finding.get("details", {}).get("evidence_examples", [])
        item["benign_explanations_checked"] = BENIGN.get(error_type, ["rounding", "design axis", "export formatting"])
        item["rank_score"] = float(finding.get("rank_score", finding.get("score", 0)))
        normalized.append(item)

    normalized.sort(key=rank_key, reverse=True)
    for i, item in enumerate(normalized, start=1):
        item["normalized_rank"] = i
    counts = Counter(item["disposition"] for item in normalized)
    highest = "none"
    if counts.get("high_confidence_fabrication_compatible_anomaly"):
        highest = "high_confidence_fabrication_compatible_anomaly"
    elif counts.get("weak_anomaly"):
        highest = "weak_anomaly"
    if not raw and column_class_count == 0:
        source_data_status = "missing_auditable_original_data"
        source_data_message = "No auditable raw/source-data numeric table was extracted or classified. This means the public materials are insufficient for stats-only fabrication-compatible anomaly screening; it does not mean the data are clean."
    elif column_class_count == 0:
        source_data_status = "no_auditable_numeric_columns"
        source_data_message = "Extracted materials did not yield auditable numeric columns. Ask the user whether to proceed with lower-confidence image/chart digitization."
    elif not raw:
        source_data_status = "no_statistical_hits"
        source_data_message = "Auditable numeric columns were classified, but no retained statistical-pattern hits were found."
    else:
        source_data_status = "auditable_numeric_data_present"
        source_data_message = "Auditable numeric data were available for stats-only screening."

    result = {
        "assessment_summary": {
            "highest_observed_tier": highest,
            "counts_by_disposition": dict(counts),
            "high_confidence_count": counts.get("high_confidence_fabrication_compatible_anomaly", 0),
            "weak_anomaly_count": counts.get("weak_anomaly", 0),
            "not_applicable_count": counts.get("not_applicable", 0),
            "source_data_status": source_data_status,
            "source_data_message": source_data_message,
            "auditable_column_count": column_class_count,
            "raw_statistical_hit_count": len(raw),
        },
        "normalized_findings": normalized,
        "context_leads": context.get("context_leads", []),
        "notes": [
            "Fabrication-compatible anomaly means a statistical pattern that is difficult to reconcile with ordinary measurement generation without further source-record explanation.",
            "It is not proof of fabrication.",
        ],
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(normalized)} normalized findings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
