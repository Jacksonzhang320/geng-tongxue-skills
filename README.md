# geng-tongxue-skills

Codex skill collection for screening paper-associated numeric data and source-data workbooks for statistical anomaly leads.

This repository currently contains one skill: `paper-data-forensics`. It audits supplementary tables, source-data Excel files, PDF-extracted tables, and manually digitized chart values for patterns such as terminal-digit concentration, repeated rows or values, overly regular decimals, arithmetic smoothness, Benford mismatches where applicable, and figure/source-data context mismatches. It also includes an optional image-chain branch for review leads such as whole-panel reuse, cropped/rescaled reuse, transformed reuse, and within-panel local clone patches.

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

Optional image-chain screening:

```powershell
python "$SKILL_DIR/scripts/extract_figure_images.py" --inventory "$OUT_DIR/inventory.json" --out "$OUT_DIR/image_chain/image_inventory.jsonl" --work-dir "$OUT_DIR/image_chain"
python "$SKILL_DIR/scripts/segment_panels.py" --image-inventory "$OUT_DIR/image_chain/image_inventory.jsonl" --out "$OUT_DIR/image_chain/panel_manifest.jsonl" --work-dir "$OUT_DIR/image_chain" --split-pages
python "$SKILL_DIR/scripts/audit_image_reuse.py" --panels "$OUT_DIR/image_chain/panel_manifest.jsonl" --out "$OUT_DIR/image_chain/image_findings_raw.json" --candidates-out "$OUT_DIR/image_chain/image_candidates.jsonl" --local-clone
python "$SKILL_DIR/scripts/normalize_image_findings.py" --findings "$OUT_DIR/image_chain/image_findings_raw.json" --out "$OUT_DIR/image_chain/image_findings_normalized.json"
python "$SKILL_DIR/scripts/render_image_report.py" --findings "$OUT_DIR/image_chain/image_findings_normalized.json" --out-dir "$OUT_DIR/image_chain/report"
```

For the full workflow, see `SKILL.md`.

## Notes

- Prefer raw/source-data tables over chart-digitized estimates.
- Downweight or exclude IDs, genomic coordinates, sample indices, p values, ranks, and fixed design variables.
- Treat image-chain findings as visual review leads; repeated texture, layout templates, compression, low resolution, public controls, and export workflows can create false positives.
- Reports should state limitations clearly and avoid allegations.
