#!/usr/bin/env python
"""Build a small synthetic statistical benchmark package."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    root = Path(args.out_dir).resolve()
    inputs = root / "inputs"
    oracle_dir = root / "oracle_private"
    inputs.mkdir(parents=True, exist_ok=True)
    oracle_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(1, 81):
        length = 5 + math.sin(i * 1.7) + (i % 7) * 0.07
        width = 3 + math.cos(i * 1.3) * 0.4 + (i % 11) * 0.03
        volume = length * width * width / 2
        if i in {10, 20, 30}:
            volume += 15
        rows.append(
            {
                "chr": "chr1",
                "start": 1000 + i,
                "end": 1100 + i,
                "sample_id": i,
                "day": i,
                "normal_measurement": round(10 + math.sin(i / 4) + i * 0.03, 3),
                "foci_last_digit_heap": f"{10 + math.sin(i / 4) + i * 0.03:.2f}7",
                "fluorescence_decimal_tail_heap": f"{20 + math.sin(i / 5) * 3 + (i % 13) * 0.4:.0f}.05",
                "signal_clone_group_a": round(5 + math.sin(i / 6), 4),
                "signal_clone_group_b": round(5 + math.sin(i / 6), 4),
                "smooth_measurement": round(1 + i * 0.5, 3),
                "length_mm": round(length, 3),
                "width_mm": round(width, 3),
                "volume_mm3": round(volume, 3),
                "n": 9,
                "sd": 3.0,
                "sem": 3.0 if i == 1 else 1.0,
            }
        )
    path = inputs / "neutral_source_data.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    article = root / "article.txt"
    article.write_text(
        "Synthetic neutral paper\nAbstract\nTreatment changes several source-data measurements.\nFig. 1 Source data benchmark with measurements and decoy design axes.\nData availability\nSource data are provided.\n",
        encoding="utf-8",
    )
    oracle = {
        "case_id": "synthetic_stat_benchmark",
        "min_exact_rate": 0.70,
        "min_near_rate": 0.85,
        "oracle_items": [
            {"id": "terminal_digits", "error_type": "terminal_digit_heaping", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["foci_last_digit_heap"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
            {"id": "decimal_tails", "error_type": "decimal_tail_heaping", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["fluorescence_decimal_tail_heap"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
            {"id": "clone_vector", "error_type": "clone_vector", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["signal_clone_group_a", "signal_clone_group_b"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
            {"id": "smooth", "error_type": "arithmetic_smoothness", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["smooth_measurement"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
            {"id": "formula", "error_type": "formula_mismatch", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["volume_mm3"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
            {"id": "summary", "error_type": "summary_math_inconsistency", "source_contains": "neutral_source_data.csv", "table_name": "neutral_source_data.csv", "columns": ["sem"], "expected_disposition": "high_confidence_fabrication_compatible_anomaly"},
        ],
    }
    (oracle_dir / "oracle.json").write_text(json.dumps(oracle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote synthetic benchmark to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
