# Paper Data Forensics

Codex skill for screening paper-associated numeric data for statistical anomaly leads.

It audits source-data workbooks, supplementary tables, PDF-extracted tables, and manually digitized chart values for patterns such as terminal-digit concentration, repeated rows or values, overly regular decimals, arithmetic smoothness, Benford mismatches where applicable, and figure/source-data context mismatches.

The output is a ranked lead list for human review. Findings are not proof of misconduct; they identify anomalies that need source records, experimental context, and author-side explanations.

## Contents

- `SKILL.md`: Codex skill instructions.
- `scripts/`: extraction, classification, numeric auditing, normalization, and report rendering scripts.
- `agents/`: optional agent metadata.

## Manual Use

```powershell
$SKILL_DIR = "<path-to-this-repo>"
$OUT_DIR = "<analysis-output-dir>"

python "$SKILL_DIR/scripts/inventory_inputs.py" --root <input_dir> --out "$OUT_DIR/inventory.json"
python "$SKILL_DIR/scripts/extract_tables.py" --inventory "$OUT_DIR/inventory.json" --out "$OUT_DIR/extracted_tables.jsonl"
python "$SKILL_DIR/scripts/audit_numeric_patterns.py" --tables "$OUT_DIR/extracted_tables.jsonl" --out "$OUT_DIR/findings_raw.json"
```

For the full workflow, see `SKILL.md`.

## Notes

- Prefer raw/source-data tables over chart-digitized estimates.
- Downweight or exclude IDs, genomic coordinates, sample indices, p values, ranks, and fixed design variables.
- Reports should state limitations clearly and avoid allegations.
