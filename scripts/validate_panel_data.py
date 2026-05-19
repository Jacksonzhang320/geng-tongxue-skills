#!/usr/bin/env python
"""Build context-aware leads from article context, mappings, and classified source data."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_json(path: str | None, default: Any) -> Any:
    if not path:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lead(kind: str, priority: str, score: float, summary: str, evidence: dict[str, Any], suggestion: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "priority": priority,
        "context_score": round(score, 3),
        "summary": summary,
        "evidence": evidence,
        "review_suggestion": suggestion,
    }


def priority(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 45:
        return "Medium"
    return "Low"


def detectable_correction_like_notices(context: dict[str, Any], reveal_notice_figures: bool = False) -> list[dict[str, Any]]:
    out = []
    for notice in context.get("notices", []):
        text = notice.get("text", "")
        if re.search(r"figure preparation|mistakenly|inadvertently|incorrect|corrected", text, re.I):
            figs = sorted(set(re.findall(r"(?:Extended Data Fig\.|Fig\.)\s*\d+[a-z]?", text)))
            score = 95 if figs else 75
            if reveal_notice_figures:
                evidence = {"notice_kind": notice.get("kind"), "notice_text": text}
                evidence["mentioned_figures"] = figs
            else:
                redacted = re.sub(r"(?:Extended Data Fig\.|Fig\.)\s*\d+[a-z]?", "[figure redacted]", text)
                redacted = re.sub(r"\b(?:DAPI|Merge|WT|KI|HDAC6|sh\s*Tet2|shNC|ΔSE14|0\.41|48 h|60 h)\b", "[detail redacted]", redacted, flags=re.I)
                evidence = {"notice_kind": notice.get("kind"), "notice_text_redacted": redacted}
                evidence["mentioned_figures"] = "redacted_for_blind_benchmark"
            out.append(
                lead(
                    "article_notice",
                    priority(score),
                    score,
                    "文章自身包含图像/图版准备相关更正或提示，应作为 benchmark oracle 或优先复核上下文，而不是直接当作新发现。",
                    evidence,
                    "验证流程中不要把具体图号泄露给盲测 agent；主流程最后用它们评估命中率。",
                )
            )
    return out


def source_data_coverage_leads(tables: list[dict[str, Any]], mappings: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    mapped_figs = {m.get("figure_id") for m in mappings if m.get("figure_id")}
    caption_figs = {f.get("figure_id") for f in context.get("figures", []) if f.get("figure_id")}
    out = []
    for fig in sorted(caption_figs - mapped_figs):
        score = 40
        out.append(
            lead(
                "source_data_coverage",
                priority(score),
                score,
                f"{fig} 有图注但未自动映射到 Source Data 表。",
                {"figure_id": fig},
                "人工确认该图是否有 source data，或是否被合并在其他工作表中。",
            )
        )
    return out


def column_context_leads(classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    by_table = defaultdict(list)
    for cls in classes:
        by_table[(cls.get("source_path"), cls.get("table_name"), cls.get("figure_id"))].append(cls)
    for (source, table, figure_id), cols in by_table.items():
        eligible = [c for c in cols if c.get("homepage_eligible") and c.get("numeric_n", 0) >= 5]
        excluded = [c for c in cols if not c.get("homepage_eligible") and c.get("numeric_n", 0) >= 5]
        if figure_id and eligible:
            score = 55 + min(20, len(eligible) * 2)
            out.append(
                lead(
                    "mapped_experimental_source_data",
                    priority(score),
                    score,
                    f"{figure_id} 的 source data 含 {len(eligible)} 个可审计实验测量/数值列。",
                    {
                        "source_path": source,
                        "table_name": table,
                        "figure_id": figure_id,
                        "eligible_columns": [c["column"] for c in eligible[:12]],
                        "excluded_column_types": dict(Counter(c["column_type"] for c in excluded)),
                    },
                    "优先复算这些列对应 panel 的均值、误差条、样本量和组别标签；不要让坐标/ID/p值列进入首页。",
                )
            )
    return out


def duplicate_label_leads(tables: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for table_i, table in enumerate(tables):
        rows = table.get("rows") or []
        normalized = []
        for row in rows:
            vals = tuple(str(v).strip() for v in row if str(v).strip())
            if vals:
                normalized.append(vals)
        counts = Counter(normalized)
        repeated = [row for row, count in counts.items() if count > 1 and len(row) >= 2]
        if not repeated:
            continue
        mapping = mappings[table_i] if table_i < len(mappings) else {}
        score = 35 if not mapping.get("figure_id") else 50
        out.append(
            lead(
                "repeated_label_or_header_rows",
                priority(score),
                score,
                "Source data 中存在重复的非空标签/表头行，可能是多 panel 合并格式，也可能隐藏标签错配风险。",
                {
                    "source_path": table.get("source_path"),
                    "table_name": table.get("table_name"),
                    "figure_id": mapping.get("figure_id", ""),
                    "repeated_row_examples": [list(r) for r in repeated[:5]],
                },
                "人工确认重复标签对应的 panel 边界，检查相邻 panel 的组名、时间点和图像标签是否错位。",
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", required=True)
    parser.add_argument("--mappings", required=True)
    parser.add_argument("--classes", required=True)
    parser.add_argument("--context")
    parser.add_argument("--reveal-notice-figures", action="store_true", help="Include correction-mentioned figure IDs in leads; do not use for blind benchmarks")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    tables = load_jsonl(Path(args.tables))
    mappings = load_json(args.mappings, {}).get("mappings", [])
    classes = load_json(args.classes, {}).get("column_classes", [])
    context = load_json(args.context, {})

    leads = []
    leads.extend(detectable_correction_like_notices(context, args.reveal_notice_figures))
    leads.extend(source_data_coverage_leads(tables, mappings, context))
    leads.extend(column_context_leads(classes))
    leads.extend(duplicate_label_leads(tables, mappings))
    leads.sort(key=lambda x: x.get("context_score", 0), reverse=True)
    for i, item in enumerate(leads, start=1):
        item["context_rank"] = i

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"context_lead_count": len(leads), "context_leads": leads}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(leads)} context-aware leads to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
