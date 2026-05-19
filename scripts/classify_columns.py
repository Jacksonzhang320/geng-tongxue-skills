#!/usr/bin/env python
"""Classify extracted table columns and decide which checks are eligible."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


NUM_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def strict_numeric_token(value: Any) -> str | None:
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "na", "n/a", "none", "null"}:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    return text if NUM_RE.fullmatch(text) else None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def numeric_values(rows: list[list[Any]], col_idx: int) -> list[float]:
    vals = []
    for row in rows:
        if col_idx >= len(row):
            continue
        token = strict_numeric_token(row[col_idx])
        if token is None:
            continue
        try:
            val = float(token)
        except ValueError:
            continue
        if math.isfinite(val):
            vals.append(val)
    return vals


def is_index_like(values: list[float]) -> bool:
    if len(values) < 5:
        return False
    unique = len(set(values))
    if unique < 5:
        return False
    diffs = [round(values[i + 1] - values[i], 8) for i in range(min(len(values) - 1, 50))]
    return all(abs(d - 1) < 1e-8 for d in diffs)


def classify(name: str, table_name: str, context: str, values: list[float]) -> tuple[str, list[str], str, str]:
    text = re.sub(r"[_\-]+", " ", f"{name} {context} {table_name}".lower())
    n = len(values)

    coordinate_hit = re.search(r"\b(seqnames|chr|chrom|start|end|strand|position|coordinate|tss|entrez|gene id|gene names?|nearest gene|protein ids?|majority protein|protein names?|accession|locus)\b", text)
    coordinate_hit = coordinate_hit or (re.search(r"\bwidth\b", text) and re.search(r"\b(region|seqnames|chr|chrom|strand|tss)\b", text))
    if coordinate_hit:
        return "genomic_or_identifier", [], "not_applicable", "Coordinate, identifier, or annotation field; digit/Benford/regularity tests are not evidence of fabrication."
    if re.search(r"\b(padj|p\.?value|p value|qvalue|fdr|score|rank|count|unique peptides?|razor.*peptides?|ms/ms|sequence coverage|annotation|term|go:|distance to nearest)\b", text):
        return "derived_stat_or_annotation", [], "not_applicable", "Derived statistic, count, enrichment result, rank, or annotation field; raw digit-pattern tests are not applicable."
    if re.search(r"\b(sample|mouse|number|no\.|day|time|dose|val\s*\(|concentration|um|µm|μm|mmol|hour|vr\s*\(|group id)\b", text) or is_index_like(values):
        return "design_or_sample_axis", [], "not_applicable", "Sample identifier, time point, dose, or fixed design axis; regular numeric spacing is expected."
    if n < 5:
        return "too_few_numeric_values", [], "not_applicable", "Too few numeric values for statistical-pattern screening."
    if n > 1000 and re.search(r"\b(region|binding|peak|chip|rna-seq|wgbs|mab-seq|ace-seq|go analysis|dependent genes|all hyper|sequencing)\b", text):
        return "large_structured_table", [], "not_applicable", "Large omics/region table; screen only explicitly identified plotted measurements, not all structured rows."
    if re.fullmatch(r"\s*(n|mean|sd|sem|std|stdev|standard deviation|standard error)\s*", str(name).lower()):
        return "summary_statistic", ["summary_math_inconsistency"], "limited", "Summary-statistic field; raw digit, decimal-tail, and duplicate screens are not applicable, but SD/SEM/n consistency can be checked."

    measurement_re = r"\b(volume|weight|length|width|tumou?r|foci|tail|fluorescence|relative|level|5hmc|5mc|5fc|5cac|cpm|intensity|ratio|fold|location|cell|fraction|valine|mean|sd|sem|percent|percentage|normalized|signal|measurement)\b"
    if re.search(measurement_re, text):
        methods = ["duplicate_values", "decimal_tail_regularity", "clone_vector", "formula_mismatch", "summary_math_inconsistency"]
        if n >= 10:
            methods.append("last_digit_distribution")
        if n >= 50 and any(v > 0 for v in values) and max(abs(v) for v in values if v != 0) / max(min(abs(v) for v in values if v != 0), 1e-12) >= 100:
            methods.append("benford_first_digit")
        return "experimental_measurement", methods, "applicable", "Experimental measurement or quantitative source-data field; screen with precision and context constraints."

    if n >= 200:
        return "large_structured_table", [], "not_applicable", "Large structured numeric table with unclear measurement semantics; do not headline without manual column identification."
    return "numeric_unknown", ["duplicate_values", "decimal_tail_regularity"], "limited", "Numeric semantics are unclear; only weak auxiliary screening is allowed."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", required=True)
    parser.add_argument("--mappings")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    tables = load_jsonl(Path(args.tables))
    mappings = {}
    if args.mappings:
        map_data = json.loads(Path(args.mappings).read_text(encoding="utf-8"))
        mappings = {m["table_index"]: m for m in map_data.get("mappings", [])}

    classes = []
    for table_i, table in enumerate(tables):
        columns = table.get("columns") or []
        contexts = table.get("column_contexts") or ["" for _ in columns]
        rows = table.get("rows") or []
        for col_i, col in enumerate(columns):
            values = numeric_values(rows, col_i)
            context = contexts[col_i] if col_i < len(contexts) else ""
            col_type, eligible, applicability, reason = classify(str(col), table.get("table_name", ""), context, values)
            mapping = mappings.get(table_i, {})
            classes.append(
                {
                    "table_index": table_i,
                    "column": str(col),
                    "column_index": col_i,
                    "column_context": context,
                    "source_path": table.get("source_path"),
                    "table_name": table.get("table_name"),
                    "figure_id": mapping.get("figure_id", ""),
                    "panels": mapping.get("panels", []),
                    "numeric_n": len(values),
                    "unique_n": len(set(round(v, 10) for v in values)),
                    "column_type": col_type,
                    "applicability": applicability,
                    "eligible_methods": eligible,
                    "eligibility_reason": reason,
                    "homepage_eligible": applicability == "applicable",
                }
            )
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"column_classes": classes}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(classes)} column classifications to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
