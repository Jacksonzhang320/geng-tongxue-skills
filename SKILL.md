---
name: paper-data-forensics
description: Use when checking academic paper raw data, supplementary tables, PDF tables, chart-derived data, or numeric figures for statistical irregularities such as last-digit anomalies, overly tidy decimals, duplicate/clone patterns, arithmetic progressions, group-level inconsistencies, Benford mismatches, or suspiciously regular data. Produces ranked leads and reproducible evidence, not allegations or conclusions of fraud.
---

# Paper Data Forensics

Use this skill to audit paper-associated numeric data, source-data workbooks, article claims, figure captions, and figure/source-data consistency. The primary output is a context-aware lead list for human review. Never state that anomalies prove fraud; use "anomaly", "lead", "mismatch", "needs explanation", or "requires source-data review".

## Workflow

Set the skill directory first when running scripts manually:
```powershell
$SKILL_DIR = "<path-to-this-skill>"
```

1. Extract article context first when an article URL/PDF text/HTML is available:
   ```powershell
   python "$SKILL_DIR/scripts/extract_article_context.py" --article-url <article_url> --out <out_dir>/article_context.json
   ```
2. Inventory inputs:
   ```powershell
   python "$SKILL_DIR/scripts/inventory_inputs.py" --root <input_dir> --out <out_dir>/inventory.json
   ```
3. Extract structured numeric tables:
   ```powershell
   python "$SKILL_DIR/scripts/extract_tables.py" --inventory <out_dir>/inventory.json --out <out_dir>/extracted_tables.jsonl
   ```
4. Map tables to figures and classify columns before ranking:
   ```powershell
   python "$SKILL_DIR/scripts/map_source_data_to_figures.py" --tables <out_dir>/extracted_tables.jsonl --context <out_dir>/article_context.json --out <out_dir>/figure_table_map.json
   python "$SKILL_DIR/scripts/classify_columns.py" --tables <out_dir>/extracted_tables.jsonl --mappings <out_dir>/figure_table_map.json --out <out_dir>/column_classes.json
   python "$SKILL_DIR/scripts/validate_panel_data.py" --tables <out_dir>/extracted_tables.jsonl --mappings <out_dir>/figure_table_map.json --classes <out_dir>/column_classes.json --context <out_dir>/article_context.json --out <out_dir>/context_leads.json
   ```
   If extraction/classification finds no raw/source-data tables and no auditable numeric columns, stop and tell the user explicitly that public materials lack auditable original data. Ask whether to continue with lower-confidence image/chart digitization or to stop; do not imply that zero findings means no problem.
5. Audit raw numeric patterns as an appendix:
   ```powershell
   python "$SKILL_DIR/scripts/audit_numeric_patterns.py" --tables <out_dir>/extracted_tables.jsonl --out <out_dir>/findings_raw.json
   ```
6. Normalize statistical hits into clear dispositions:
   ```powershell
   python "$SKILL_DIR/scripts/normalize_findings.py" --findings <out_dir>/findings_raw.json --classes <out_dir>/column_classes.json --context-leads <out_dir>/context_leads.json --out <out_dir>/findings_normalized.json
   ```
7. Render a Chinese Markdown report plus evidence plots:
   ```powershell
   python "$SKILL_DIR/scripts/render_report.py" --ranked <out_dir>/findings_normalized.json --out-dir <out_dir>/report
   ```

Optional image-chain audit, run after `inventory_inputs.py` when PDF pages, figure images, or supplementary images should be screened for visual reuse leads:
```powershell
python "$SKILL_DIR/scripts/extract_figure_images.py" --inventory <out_dir>/inventory.json --out <out_dir>/image_chain/image_inventory.jsonl --work-dir <out_dir>/image_chain
python "$SKILL_DIR/scripts/segment_panels.py" --image-inventory <out_dir>/image_chain/image_inventory.jsonl --out <out_dir>/image_chain/panel_manifest.jsonl --work-dir <out_dir>/image_chain --split-pages
python "$SKILL_DIR/scripts/audit_image_reuse.py" --panels <out_dir>/image_chain/panel_manifest.jsonl --out <out_dir>/image_chain/image_findings_raw.json --candidates-out <out_dir>/image_chain/image_candidates.jsonl --local-clone
python "$SKILL_DIR/scripts/normalize_image_findings.py" --findings <out_dir>/image_chain/image_findings_raw.json --out <out_dir>/image_chain/image_findings_normalized.json
python "$SKILL_DIR/scripts/render_image_report.py" --findings <out_dir>/image_chain/image_findings_normalized.json --out-dir <out_dir>/image_chain/report
```

## Source Priority

Prefer sources in this order: raw tables, supplementary tables, PDF-extracted tables, then image/chart-derived estimates. For images, place manually digitized or external-tool point values beside the image as `<image_stem>.points.csv` or `<image_stem>.points.tsv`; these records are labeled `estimated`. Image or chart-derived values must be treated only as leads.

## What To Look For

- Last-digit distribution: missing digits, excessive concentration, chi-square or simulation p-values.
- Decimal regularity: excessive `.00`, `.50`, `.05`, same tail digits, or fixed decimal precision.
- Duplicate and clone patterns: repeated rows, repeated columns, cross-group identical values.
- Arithmetic and smoothness patterns: fixed step sizes, sorted values with too-regular intervals, over-smoothed sequences.
- Group-level inconsistencies: suspiciously tidy mean/SD/SEM/n relations when columns are identifiable.
- Benford/first-digit checks only when values span enough orders of magnitude and are not constrained by design.
- Article/source-data mismatches: figure captions, panel labels, group names, time points, sample counts, and source-data workbooks disagree.
- Image-chain leads: whole-panel reuse, cropped/rescaled reuse, rotated/flipped reuse, within-panel local clone patches, and blot/gel lane similarity. Treat visual hits as review leads, not proof.
- Benchmark recovery: public corrections or editor notes may be used after blind analysis to score whether the workflow recovered known issue families.
- Fabrication-compatible disposition: every raw hit must be normalized to `not_applicable`, `weak_anomaly`, or `high_confidence_fabrication_compatible_anomaly` before it appears in a report.

## Column Eligibility

Never let raw statistical hits dominate the first page without data-type filtering. Downweight or exclude genomic coordinates, IDs, sample indices, p values, adjusted p values, GO counts, ranks, fixed dose/time gradients, and other design variables. Prefer context-aware review of experimental measurements such as foci percentages, tail moment, tumour volume/weight, fluorescence, UPLC-MS/MS values, dot-blot quantification, qPCR fold change, cell fractions, and relative localization.

## Blind Benchmark Validation

When using a known problematic paper as a benchmark, keep the oracle separate from the audit prompt. A validation agent can inspect article text, source data, or images, but should not be told the known corrected panel IDs. After blind lead generation, use `benchmark_known_cases.py` to score true positives, near misses, and missed oracle items.

## Reporting Rules

- Rank leads as High, Medium, or Low risk based on source confidence, sample size, and number of independent anomaly families.
- Include file path, table/sheet name, column name, method, sample size, p-value/statistic when available, and a human review suggestion.
- Report exact evidence examples: row index, Excel-style cell, column, raw value, and nearby group/condition labels.
- Start with a Chinese assessment-summary section that directly states whether high-confidence fabrication-compatible anomalies were found.
- If no auditable raw/source-data numeric table is available, the summary must say this directly and ask for the user's next-step decision before any image/chart-derived analysis.
- Always include limitations: statistical anomalies are not proof of misconduct; rounding and small samples can create false positives; source records and experimental context are required.
- Image-chain reports must include visual evidence images for retained findings and must state that repeated texture, layout templates, compression, low resolution, public controls, and figure-export workflows can create false positives.
- For plots, export both `.png` and `.svg` with the same stem. Do not export PDF by default.

## Long Runs

For batches expected to exceed 2 minutes, use `$long-task-runner`: small trial first, then background run with `run.log`, `progress.json`, checkpoints, PID record, and resume behavior. Do not delete expensive intermediate results unless the user explicitly asks.
