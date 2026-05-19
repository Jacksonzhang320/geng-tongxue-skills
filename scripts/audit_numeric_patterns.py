#!/usr/bin/env python
"""Audit numeric tables for fabrication-compatible statistical anomalies."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean, pstdev, stdev
from typing import Any


NUM_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def strict_numeric_token(value: Any) -> str | None:
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "na", "n/a", "none", "null"}:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    return text if NUM_RE.fullmatch(text) else None


def as_decimal(value: Any) -> Decimal | None:
    token = strict_numeric_token(value)
    if token is None:
        return None
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def finite_float(value: Decimal) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def excel_col(index: int) -> str:
    index += 1
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def numeric_token(value: Any) -> str | None:
    return strict_numeric_token(value)


def last_printed_digit(value: Any) -> str | None:
    token = numeric_token(value)
    if token is None:
        return None
    if "e" in token.lower():
        dec = as_decimal(token)
        token = format(dec, "f") if dec is not None else token
    digits = [c for c in token if c.isdigit()]
    return digits[-1] if digits else None


def decimal_tail(value: Any, places: int = 2) -> str | None:
    token = numeric_token(value)
    if token is None:
        return None
    if "e" in token.lower():
        dec = as_decimal(token)
        token = format(dec, "f") if dec is not None else token
    if "." not in token:
        return "0" * places
    tail = token.split(".", 1)[1]
    return (tail + "0" * places)[:places]


def decimal_places(value: Any) -> int | None:
    token = numeric_token(value)
    if token is None or "e" in token.lower():
        return None
    return len(token.split(".", 1)[1]) if "." in token else 0


def integer_or_export_precision_zero(values: list[dict[str, Any]]) -> bool:
    tokens = [numeric_token(v["raw"]) for v in values]
    tokens = [t for t in tokens if t is not None]
    if not tokens:
        return False
    integer_like = [bool(re.fullmatch(r"[-+]?\d+(?:\.0+)?", t)) for t in tokens]
    return sum(integer_like) / len(tokens) >= 0.90


def chi_square_p_approx(stat: float, df: int) -> float:
    if df <= 0:
        return 1.0
    z = ((stat / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return 0.5 * math.erfc(z / math.sqrt(2))


def row_label(row: list[str], columns: list[str], focus_i: int) -> dict[str, str]:
    labels = {}
    for i, name in enumerate(columns[: min(len(columns), 8)]):
        if i == focus_i or i >= len(row):
            continue
        value = str(row[i]).strip()
        if value and not NUM_RE.fullmatch(value.replace(",", "")):
            labels[name] = value[:80]
    return labels


def evidence_example(table: dict[str, Any], row_i: int, col_i: int, value: Any) -> dict[str, Any]:
    rows = table.get("rows") or []
    columns = table.get("columns") or []
    row_numbers = table.get("row_numbers") or []
    cells = table.get("cell_addresses") or []
    row_no = row_numbers[row_i] if row_i < len(row_numbers) else row_i + 1
    cell = cells[row_i][col_i] if row_i < len(cells) and col_i < len(cells[row_i]) else f"{excel_col(col_i)}{row_no}"
    return {
        "row_index": int(row_no),
        "cell": cell,
        "column": columns[col_i] if col_i < len(columns) else f"col_{col_i + 1}",
        "value": str(value),
        "nearby_labels": row_label(rows[row_i], columns, col_i) if row_i < len(rows) else {},
    }


def numeric_columns(table: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows = table.get("rows") or []
    columns = table.get("columns") or []
    out: dict[str, list[dict[str, Any]]] = {}
    for col_i, col in enumerate(columns):
        values = []
        for row_i, row in enumerate(rows):
            raw = row[col_i] if col_i < len(row) else ""
            dec = as_decimal(raw)
            if dec is None:
                continue
            flt = finite_float(dec)
            if flt is None:
                continue
            values.append({"raw": raw, "decimal": dec, "float": flt, "row_i": row_i, "col_i": col_i})
        if len(values) >= 5:
            out[str(col)] = values
    return out


def finding(table: dict[str, Any], column: str, method: str, severity: str, score: float, n: int, summary: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": table.get("source_path"),
        "source_kind": table.get("source_kind", "unknown"),
        "source_confidence": table.get("source_confidence", "unknown"),
        "table_name": table.get("table_name", ""),
        "column": column,
        "method": method,
        "anomaly_family": method,
        "severity": severity,
        "score": round(float(score), 3),
        "n": int(n),
        "summary": summary,
        "details": details,
    }


def severity_from_score(score: float, n: int, confidence: str) -> str:
    if n < 10 or confidence in {"metadata_only", "not_extracted"}:
        return "Low"
    if score >= 80 and confidence in {"raw_table", "pdf_extracted"}:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def examples_for_items(table: dict[str, Any], items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return [evidence_example(table, item["row_i"], item["col_i"], item["raw"]) for item in items[:limit]]


def audit_last_digits(table: dict[str, Any], column: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = [(last_printed_digit(v["raw"]), v) for v in values]
    pairs = [(d, v) for d, v in pairs if d is not None]
    n = len(pairs)
    if n < 10:
        return []
    counts = Counter(d for d, _ in pairs)
    expected = n / 10
    chi = sum((counts.get(str(d), 0) - expected) ** 2 / expected for d in range(10))
    p = chi_square_p_approx(chi, 9)
    max_digit, max_count = max(counts.items(), key=lambda kv: kv[1])
    missing = [str(d) for d in range(10) if counts.get(str(d), 0) == 0]
    if max_digit == "0" and max_count / n >= 0.95 and integer_or_export_precision_zero([v for _, v in pairs]):
        return []
    score = min(100, -10 * math.log10(max(p, 1e-12)) + max(0, max_count / n - 0.25) * 120 + len(missing) * 4)
    if p < 0.01 or max_count / n >= 0.35 or (n >= 30 and missing):
        examples = examples_for_items(table, [v for d, v in pairs if d == max_digit])
        return [
            finding(
                table,
                column,
                "last_digit_distribution",
                severity_from_score(score, n, table.get("source_confidence", "")),
                score,
                n,
                f"Last printed digit is non-uniform: digit {max_digit} appears {max_count}/{n}; {len(missing)} digits are absent.",
                {"counts": dict(sorted(counts.items())), "chi_square": round(chi, 4), "p_approx": p, "missing_digits": missing, "evidence_examples": examples},
            )
        ]
    return []


def audit_decimal_tails(table: dict[str, Any], column: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs = [(decimal_tail(v["raw"], 2), v) for v in values]
    pairs = [(t, v) for t, v in pairs if t is not None]
    places = [decimal_places(v["raw"]) for v in values]
    places = [p for p in places if p is not None]
    n = len(pairs)
    if n < 10:
        return []
    counts = Counter(t for t, _ in pairs)
    common_tail, common_count = max(counts.items(), key=lambda kv: kv[1])
    tidy = sum(counts.get(t, 0) for t in ["00", "50", "05"])
    fixed_precision = max(Counter(places).values()) / len(places) if places else 0
    score = min(100, max(0, common_count / n - 0.20) * 140 + max(0, tidy / n - 0.35) * 100 + max(0, fixed_precision - 0.90) * 30)
    if common_count / n >= 0.35 or tidy / n >= 0.55 or (n >= 30 and fixed_precision >= 0.98):
        examples = examples_for_items(table, [v for t, v in pairs if t == common_tail])
        return [
            finding(
                table,
                column,
                "decimal_tail_regularity",
                severity_from_score(score, n, table.get("source_confidence", "")),
                score,
                n,
                f"Two-digit decimal tails are overly regular: tail {common_tail} appears {common_count}/{n}; tidy tails .00/.50/.05 appear {tidy}/{n}.",
                {"top_tails": dict(counts.most_common(10)), "tidy_tail_count": tidy, "fixed_precision_fraction": fixed_precision, "evidence_examples": examples},
            )
        ]
    return []


def audit_duplicates(table: dict[str, Any], column: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(values)
    if n < 10:
        return []
    groups: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for value in values:
        groups[round(value["float"], 10)].append(value)
    total_unique_values = len(groups)
    repeated_any = {k: group for k, group in groups.items() if len(group) >= 2}
    repeated = {k: group for k, group in groups.items() if len(group) >= 3}
    repeat_count = sum(len(group) for group in repeated_any.values())
    if repeated or repeat_count / n >= 0.35:
        top_value, top_group = max(groups.items(), key=lambda kv: len(kv[1]))
        top_repeated_values = [
            {"value": str(value), "count": len(group), "fraction": round(len(group) / n, 4)}
            for value, group in sorted(repeated_any.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
        ]
        score = min(100, len(repeated) * 12 + repeat_count / n * 80)
        return [
            finding(
                table,
                column,
                "duplicate_values",
                severity_from_score(score, n, table.get("source_confidence", "")),
                score,
                n,
                f"Repeated numeric values are concentrated: {total_unique_values} unique values in {n} observations; {len(repeated_any)} distinct values repeat; {repeat_count}/{n} observations belong to repeated-value groups; most repeated value {top_value} occurs {len(top_group)} times ({len(top_group) / n:.1%}).",
                {
                    "total_unique_values": total_unique_values,
                    "distinct_repeated_values": len(repeated_any),
                    "distinct_repeated_values_ge3": len(repeated),
                    "repeated_observation_count": repeat_count,
                    "repeated_observation_fraction": round(repeat_count / n, 4),
                    "top_repeated_values": top_repeated_values,
                    "repeated_values_ge3": {str(k): len(v) for k, v in repeated.items()},
                    "repeat_count": repeat_count,
                    "evidence_examples": examples_for_items(table, top_group),
                },
            )
        ]
    return []


def audit_arithmetic(table: dict[str, Any], column: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    n = len(values)
    if n < 8:
        return []
    ordered = [v["float"] for v in values]
    diffs = [round(ordered[i + 1] - ordered[i], 10) for i in range(len(ordered) - 1)]
    nonzero = [d for d in diffs if d != 0]
    if len(nonzero) < 5:
        return []
    counts = Counter(nonzero)
    common_step, common_count = max(counts.items(), key=lambda kv: kv[1])
    diff_mean = abs(mean(nonzero)) or 1e-12
    cv = pstdev(nonzero) / diff_mean if len(nonzero) > 1 else 0.0
    if common_count / len(nonzero) >= 0.55 or cv < 0.08:
        score = min(100, common_count / len(nonzero) * 80 + max(0, 0.15 - cv) * 180)
        ex_items = []
        for i, d in enumerate(diffs):
            if d == common_step:
                ex_items.extend([values[i], values[i + 1]])
            if len(ex_items) >= 8:
                break
        return [
            finding(
                table,
                column,
                "arithmetic_or_over_smooth_sequence",
                severity_from_score(score, n, table.get("source_confidence", "")),
                score,
                n,
                f"Row-order values are overly regular: common adjacent step {common_step} occurs {common_count}/{len(nonzero)}; delta CV={cv:.4f}.",
                {"common_step": common_step, "common_step_count": common_count, "diff_cv": cv, "evidence_examples": examples_for_items(table, ex_items)},
            )
        ]
    return []


def audit_benford(table: dict[str, Any], column: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nums = [abs(v["float"]) for v in values if abs(v["float"]) > 0]
    n = len(nums)
    if n < 50 or not nums or max(nums) / min(nums) < 100:
        return []
    first_digits = []
    for x in nums:
        while x >= 10:
            x /= 10
        while x < 1:
            x *= 10
        first_digits.append(str(int(x)))
    counts = Counter(first_digits)
    expected = {str(d): n * math.log10(1 + 1 / d) for d in range(1, 10)}
    chi = sum((counts.get(str(d), 0) - expected[str(d)]) ** 2 / expected[str(d)] for d in range(1, 10))
    p = chi_square_p_approx(chi, 8)
    if p < 0.01:
        score = min(100, -10 * math.log10(max(p, 1e-12)))
        top_digit = max(counts.items(), key=lambda kv: kv[1])[0]
        eligible_examples = []
        for v in values:
            x = abs(v["float"])
            if x <= 0:
                continue
            while x >= 10:
                x /= 10
            while x < 1:
                x *= 10
            if str(int(x)) == top_digit:
                eligible_examples.append(v)
        examples = examples_for_items(table, eligible_examples[:8])
        return [
            finding(
                table,
                column,
                "benford_first_digit",
                severity_from_score(score, n, table.get("source_confidence", "")),
                score,
                n,
                f"First digits deviate from Benford expectation: p={p:.3g}.",
                {"counts": dict(sorted(counts.items())), "chi_square": round(chi, 4), "p_approx": p, "evidence_examples": examples},
            )
        ]
    return []


def audit_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    rows = table.get("rows") or []
    if len(rows) < 5:
        return []
    normalized = [(i, tuple(str(v).strip() for v in row)) for i, row in enumerate(rows) if any(str(v).strip() for v in row)]
    counts = Counter(row for _, row in normalized)
    repeats = [row for row, count in counts.items() if count > 1]
    if not repeats:
        return []
    repeat_rows = sum(counts[row] for row in repeats)
    examples = []
    for row in repeats[:3]:
        for row_i, candidate in normalized:
            if candidate == row:
                examples.append({"row_index": (table.get("row_numbers") or [])[row_i] if row_i < len(table.get("row_numbers") or []) else row_i + 1, "values": list(row)[:12]})
            if len(examples) >= 8:
                break
    score = min(100, repeat_rows / max(len(normalized), 1) * 90 + len(repeats) * 4)
    return [
        finding(
            table,
            "__rows__",
            "duplicate_rows",
            severity_from_score(score, len(normalized), table.get("source_confidence", "")),
            score,
            len(normalized),
            f"Repeated complete rows: {repeat_rows}/{len(normalized)} non-empty rows are part of duplicated row patterns.",
            {"duplicate_row_patterns": len(repeats), "repeat_rows": repeat_rows, "evidence_examples": examples},
        )
    ]


def audit_vector_clones(table: dict[str, Any], cols: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    items = [(name, vals) for name, vals in cols.items() if 5 <= len(vals) <= 200]
    for i, (name_a, vals_a) in enumerate(items):
        a = [round(v["float"], 8) for v in vals_a]
        for name_b, vals_b in items[i + 1 :]:
            if len(vals_b) != len(vals_a):
                continue
            b = [round(v["float"], 8) for v in vals_b]
            if len(set(a)) <= 1 or len(set(b)) <= 1:
                continue
            exact = a == b
            if exact:
                score = 95
                examples = []
                for va, vb in zip(vals_a[:4], vals_b[:4]):
                    examples.append(evidence_example(table, va["row_i"], va["col_i"], va["raw"]))
                    examples.append(evidence_example(table, vb["row_i"], vb["col_i"], vb["raw"]))
                out.append(
                    finding(
                        table,
                        f"{name_a} <> {name_b}",
                        "clone_vector",
                        "High",
                        score,
                        len(a),
                        f"Two numeric columns have identical vectors across {len(a)} rows: {name_a} and {name_b}.",
                        {"columns": [name_a, name_b], "clone_type": "exact_vector", "evidence_examples": examples},
                    )
                )
    return out


def find_column(columns: list[str], pattern: str) -> int | None:
    for i, col in enumerate(columns):
        if re.search(pattern, col, re.I):
            return i
    return None


def audit_formula_consistency(table: dict[str, Any]) -> list[dict[str, Any]]:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    length_i = find_column(columns, r"\blength")
    width_i = find_column(columns, r"\bwidth")
    volume_i = find_column(columns, r"\bvolume")
    if length_i is None or width_i is None or volume_i is None:
        return []
    mismatches = []
    for row_i, row in enumerate(rows):
        try:
            length = float(str(row[length_i]).replace(",", ""))
            width = float(str(row[width_i]).replace(",", ""))
            observed = float(str(row[volume_i]).replace(",", ""))
        except Exception:
            continue
        expected = length * width * width / 2
        tol = max(0.02, abs(expected) * 0.02)
        if abs(observed - expected) > tol:
            ex = evidence_example(table, row_i, volume_i, row[volume_i])
            ex["expected_from_formula"] = round(expected, 6)
            ex["formula"] = "length * width^2 / 2"
            mismatches.append(ex)
    if len(mismatches) >= 2:
        score = min(100, 50 + len(mismatches) * 5)
        return [
            finding(
                table,
                columns[volume_i],
                "formula_mismatch",
                severity_from_score(score, len(rows), table.get("source_confidence", "")),
                score,
                len(rows),
                f"Derived tumor volume does not match length*width^2/2 in {len(mismatches)} rows.",
                {"formula": "length * width^2 / 2", "mismatch_count": len(mismatches), "evidence_examples": mismatches[:10]},
            )
        ]
    return []


def audit_summary_math(table: dict[str, Any]) -> list[dict[str, Any]]:
    columns = table.get("columns") or []
    rows = table.get("rows") or []
    n_i = find_column(columns, r"^n$|sample\s*n")
    sd_i = find_column(columns, r"\bsd\b|std")
    sem_i = find_column(columns, r"\bsem\b|se\b")
    if n_i is None or sd_i is None or sem_i is None:
        return []
    mismatches = []
    for row_i, row in enumerate(rows):
        try:
            n = float(str(row[n_i]).replace(",", ""))
            sd = float(str(row[sd_i]).replace(",", ""))
            sem = float(str(row[sem_i]).replace(",", ""))
        except Exception:
            continue
        if n <= 1:
            continue
        expected = sd / math.sqrt(n)
        tol = max(0.001, abs(expected) * 0.03)
        if abs(sem - expected) > tol:
            ex = evidence_example(table, row_i, sem_i, row[sem_i])
            ex["expected_sem"] = round(expected, 6)
            ex["sd"] = sd
            ex["n"] = n
            mismatches.append(ex)
    if mismatches:
        score = min(100, 70 + len(mismatches) * 5)
        return [
            finding(
                table,
                columns[sem_i],
                "summary_math_inconsistency",
                "High",
                score,
                len(rows),
                f"Reported SEM is inconsistent with SD/sqrt(n) in {len(mismatches)} rows.",
                {"formula": "SEM = SD / sqrt(n)", "mismatch_count": len(mismatches), "evidence_examples": mismatches[:10]},
            )
        ]
    return []


def audit_table(table: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    if not table.get("rows"):
        return out
    cols = numeric_columns(table)
    out.extend(audit_rows(table))
    for column, values in cols.items():
        out.extend(audit_last_digits(table, column, values))
        out.extend(audit_decimal_tails(table, column, values))
        out.extend(audit_duplicates(table, column, values))
        out.extend(audit_arithmetic(table, column, values))
        out.extend(audit_benford(table, column, values))
    out.extend(audit_vector_clones(table, cols))
    out.extend(audit_formula_consistency(table))
    out.extend(audit_summary_math(table))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    findings = []
    table_count = 0
    with Path(args.tables).open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            table = json.loads(line)
            table_count += 1
            findings.extend(audit_table(table))

    result = {"table_records": table_count, "finding_count": len(findings), "findings": findings}
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audited {table_count} table records; wrote {len(findings)} findings to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
