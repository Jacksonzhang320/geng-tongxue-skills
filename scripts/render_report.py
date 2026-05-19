#!/usr/bin/env python
"""Render normalized statistical-forensics report in Chinese plus PNG/SVG evidence plots."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


DISPOSITION_CN = {
    "high_confidence_fabrication_compatible_anomaly": "高置信度、与统计编造相容的异常",
    "weak_anomaly": "弱异常线索",
    "not_applicable": "不适用/已排除",
}

ERROR_TYPE_CN = {
    "terminal_digit_heaping": "末位数字集中",
    "decimal_tail_heaping": "小数尾数集中",
    "duplicate_value_cluster": "重复值聚集",
    "duplicate_row_clone": "整行重复/克隆",
    "clone_vector": "向量克隆",
    "arithmetic_smoothness": "等差/过度平滑",
    "summary_math_inconsistency": "摘要统计数学不一致",
    "formula_mismatch": "派生公式不一致",
    "benford_misfit": "Benford/首位数字偏离",
}

TERM_CN = {
    "rounding": "四舍五入",
    "instrument precision": "仪器精度",
    "manual thresholding": "人工阈值",
    "bounded/discrete data": "有界或离散数据",
    "export formatting": "导出格式",
    "instrument resolution": "仪器分辨率",
    "plateau/limit of detection": "平台期或检出限",
    "template/header duplication": "模板或表头重复",
    "intentional replicate labels": "有意重复的重复样本标签",
    "merged panel formatting": "合并面板造成的格式重复",
    "shared normalization control": "共享归一化对照",
    "copied design axis": "复制的设计轴",
    "intentional repeated standard curve": "有意重复的标准曲线",
    "fixed design axis": "固定设计轴",
    "interpolation": "插值",
    "instrument step size": "仪器步长",
    "reported SD vs SEM ambiguity": "SD/SEM 标注歧义",
    "different replicate definition": "重复样本定义不同",
    "different formula convention": "公式约定不同",
    "unit conversion": "单位换算",
    "thresholding": "阈值处理",
    "non-Benford experimental design": "不适用 Benford 的实验设计",
    "design axis": "设计轴",
}


def try_import_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        from matplotlib import font_manager
        import matplotlib.pyplot as plt

        available = {font.name for font in font_manager.fontManager.ttflist}
        for font_name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]:
            if font_name in available:
                matplotlib.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
                break
        matplotlib.rcParams["axes.unicode_minus"] = False
        return plt
    except Exception:
        return None


def plot_counts(title: str, labels: list[str], values: list[int], out_dir: Path, stem: str) -> list[str]:
    plt = try_import_matplotlib()
    if plt is None:
        return []
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    ax.bar(labels, values, color="#4C78A8")
    ax.set_title(title)
    ax.set_ylabel("计数")
    fig.tight_layout()
    paths = []
    for ext in [".png", ".svg"]:
        path = out_dir / f"{stem}{ext}"
        fig.savefig(path, dpi=180)
        paths.append(str(path))
    plt.close(fig)
    return paths


def evidence_plot(finding: dict, out_dir: Path) -> list[str]:
    details = finding.get("details", {})
    stem = f"rank_{finding.get('normalized_rank', finding.get('rank', 0)):03d}_{finding.get('error_type', finding.get('method', 'finding'))}"
    stem = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    if finding.get("method") == "last_digit_distribution" and details.get("counts"):
        labels = [str(i) for i in range(10)]
        return plot_counts("末位数字分布", labels, [details["counts"].get(d, 0) for d in labels], out_dir, stem)
    if finding.get("method") == "decimal_tail_regularity" and details.get("top_tails"):
        items = list(details["top_tails"].items())[:10]
        return plot_counts("小数尾数 Top 10", [k for k, _ in items], [v for _, v in items], out_dir, stem)
    return []


def md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        clean = [str(cell).replace("\n", " ").replace("|", "\\|")[:300] for cell in row]
        out.append("| " + " | ".join(clean) + " |")
    return out


def example_rows(finding: dict, limit: int = 6) -> list[list[str]]:
    rows = []
    for ex in (finding.get("evidence_examples") or [])[:limit]:
        rows.append(
            [
                ex.get("cell", ""),
                ex.get("row_index", ""),
                ex.get("column", ""),
                ex.get("value", ""),
                json.dumps(ex.get("nearby_labels", {}), ensure_ascii=False),
            ]
        )
    return rows


def duplicate_detail_rows(finding: dict) -> list[list[str]]:
    details = finding.get("details", {})
    n = float(finding.get("n") or 0)
    rows = []
    for item in details.get("top_repeated_values", [])[:10]:
        count = int(item.get("count") or 0)
        fraction = item.get("fraction")
        if fraction is None and n:
            fraction = count / n
        rows.append([item.get("value", ""), count, f"{float(fraction):.1%}" if fraction is not None else ""])
    return rows


def cn_disposition(value: str) -> str:
    return DISPOSITION_CN.get(value, value or "未知")


def cn_error_type(value: str) -> str:
    return ERROR_TYPE_CN.get(value, value or "未知")


def cn_terms(items: list[str]) -> str:
    return "，".join(TERM_CN.get(str(item), str(item)) for item in items)


def cn_sentence(text: str | None) -> str:
    if not text:
        return ""
    s = str(text)
    patterns = [
        (
            r"Last printed digit is non-uniform: digit (\S+) appears (\d+)/(\d+); (\d+) digits are absent\.",
            r"末位数字分布不均：数字 \1 出现 \2/\3 次；缺失 \4 个数字。",
        ),
        (
            r"Two-digit decimal tails are overly regular: tail (\S+) appears (\d+)/(\d+); tidy tails \.00/\.50/\.05 appear (\d+)/(\d+)\.",
            r"两位小数尾数过于整齐：尾数 \1 出现 \2/\3 次；.00/.50/.05 这类整齐尾数出现 \4/\5 次。",
        ),
        (
            r"Repeated numeric values are concentrated: (\d+) unique values in (\d+) observations; (\d+) distinct values repeat; (\d+)/(\d+) observations belong to repeated-value groups; most repeated value ([^ ]+) occurs (\d+) times \(([^)]+)\)\.",
            r"重复值聚集：\2 个观测中共有 \1 种唯一值；其中 \3 种值发生重复；\4/\5 个观测属于重复值组；最常重复值 \6 出现 \7 次（\8）。",
        ),
        (
            r"Repeated numeric values are concentrated: (\d+)/(\d+) values belong to repeated-value groups; most repeated value ([^ ]+) occurs (\d+) times\.",
            r"重复值聚集：\1/\2 个观测属于重复值组；最常重复值 \3 出现 \4 次。",
        ),
        (
            r"Row-order values are overly regular: common adjacent step ([^ ]+) occurs (\d+)/(\d+); delta CV=([^ ]+)\.",
            r"原始行序中的数值过于规则：相邻步长 \1 出现 \2/\3 次；差分 CV=\4。",
        ),
        (
            r"First digits deviate from Benford expectation: p=([^ ]+)\.",
            r"首位数字偏离 Benford 期望：p=\1。",
        ),
        (
            r"Two numeric columns have identical vectors across (\d+) rows: (.+)\.",
            r"两个数值列在 \1 行中向量完全一致：\2。",
        ),
        (
            r"Reported SEM is inconsistent with SD/sqrt\(n\) in (\d+) rows\.",
            r"报告的 SEM 与 SD/sqrt(n) 在 \1 行中不一致。",
        ),
        (
            r"Derived tumor volume does not match length\*width\^2/2 in (\d+) rows\.",
            r"派生 tumor volume 与 length*width^2/2 在 \1 行中不一致。",
        ),
    ]
    for pattern, repl in patterns:
        s = re.sub(pattern, repl, s)

    replacements = {
        "Terminal zeros are strong but compatible with instrument/export quantization; source precision metadata is needed before treating this as high confidence.": "末位 0 集中很强，但可能由仪器精度或导出量化造成；在取得源记录/精度元数据前不能判为高置信度。",
        "Single-method or limited-context anomaly; plausible rounding/design explanations remain.": "单一方法或上下文有限的异常；四舍五入、实验设计或导出格式仍可能解释。",
        "Strong terminal-digit heaping in eligible measurement data.": "适用的测量数据中存在强末位数字集中。",
        "Strong repeated decimal-tail pattern in eligible measurement data.": "适用的测量数据中存在强小数尾数集中。",
        "Large repeated-value cluster in eligible measurement data.": "适用的测量数据中存在大量重复值聚集。",
        "Overly regular row-order step pattern in eligible measurement data.": "适用的测量数据中存在过于规则的原始行序步长。",
        "Exact clone/math/formula inconsistency in eligible source data; benign explanations still require source-record review.": "适用的源数据中存在精确克隆、数学或公式不一致；仍需源记录复核良性解释。",
        "Reported summary statistic is mathematically inconsistent with companion n/SD/SEM fields beyond tolerance.": "报告的摘要统计量与配套 n/SD/SEM 字段在容差外不一致。",
        "Column type is not eligible for this statistical test.": "该列类型不适用于此统计检测。",
        "Decimal-tail test is not applicable when the observed values are integer-only exports.": "观测值为纯整数导出时，小数尾数检测不适用。",
        "Discrete count or peptide-count field; repeated values and tidy digits are expected and not fabrication-compatible evidence by themselves.": "离散计数或 peptide-count 字段中，重复值和整齐尾数是可预期的，不能单独作为统计编造相容证据。",
        "Anonymous extracted column (col_N); header/source-data mapping is unresolved, so raw digit or smoothness hits cannot be treated as fabrication-compatible evidence.": "匿名抽取列（col_N）的表头/源数据映射未解决，原始数字或平滑性命中不能作为统计编造相容证据。",
        "Summary-statistic field; raw digit, decimal-tail, duplicate, and smoothness screens are not fabrication-compatible evidence.": "摘要统计字段中，末位数、小数尾数、重复值和平滑性筛查不构成统计编造相容证据。",
        "Clone-vector components are not both eligible experimental measurements; design axes, IDs, and summary metadata are excluded.": "向量克隆的组成列并非都属于适用的实验测量；设计轴、ID 和摘要元数据已排除。",
        "Numeric semantics are unclear; only weak auxiliary screening is allowed.": "数值语义不明确，只能作为弱辅助筛查。",
        "Coordinate, identifier, or annotation field; digit/Benford/regularity tests are not evidence of fabrication.": "坐标、ID 或注释字段；数字分布、Benford 或规则性检测不能作为编造证据。",
        "Sample identifier, time point, dose, or fixed design axis; regular numeric spacing is expected.": "样本编号、时间点、剂量或固定设计轴；规则数值间隔是预期现象。",
        "Large structured numeric table with unclear measurement semantics; do not headline without manual column identification.": "大型结构化数值表且测量语义不清；未人工确认列含义前不进入首页异常。",
        "Terminal-zero heaping in integer/export-quantized values is treated as a precision or export-format artifact, not a fabrication-compatible statistical anomaly.": "整数或导出量化值中的末位 0 集中按精度/导出格式处理，不作为统计编造相容异常。",
    }
    return replacements.get(s, s)


def finding_block(item: dict, include_examples: bool = True) -> list[str]:
    disposition = item.get("disposition", "")
    error_type = item.get("error_type", "")
    lines = [
        f"### #{item.get('normalized_rank')} {cn_disposition(disposition)} (`{disposition}`) | {cn_error_type(error_type)} (`{error_type}`) | 分数={item.get('rank_score', item.get('score'))}",
        "",
        f"- 数据来源：`{item.get('source_path')}`",
        f"- 表/Sheet：`{item.get('table_name')}`",
        f"- 列：`{item.get('column')}`；图/Panel：`{item.get('figure_id', '')}`",
        f"- 检测方法：`{item.get('method')}`；样本量 n={item.get('n')}",
        f"- 列类型：`{item.get('column_type')}`；适用性：`{item.get('applicability')}`",
        f"- 观察到的模式：{cn_sentence(item.get('summary'))}",
        f"- 裁决理由：{cn_sentence(item.get('disposition_reason'))}",
        f"- 已检查的良性解释：{cn_terms(item.get('benign_explanations_checked', []))}",
    ]
    if item.get("error_type") == "duplicate_value_cluster":
        details = item.get("details", {})
        lines.extend(
            [
                f"- 重复值概览：唯一值总数={details.get('total_unique_values', 'NA')}；发生重复的唯一值种类={details.get('distinct_repeated_values', 'NA')}；异常重复观测数={details.get('repeated_observation_count', details.get('repeat_count', 'NA'))}/{item.get('n')}",
            ]
        )
        detail_rows = duplicate_detail_rows(item)
        if detail_rows:
            lines.append("")
            lines.extend(md_table(["重复值", "出现次数", "占比"], detail_rows))
    if include_examples and item.get("evidence_examples"):
        lines.append("")
        lines.extend(md_table(["单元格", "行", "列", "原始值", "邻近标签"], example_rows(item)))
    return lines + [""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranked", required=True, help="Normalized findings JSON preferred; ranked JSON supported as fallback")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--benchmark")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--raw-top", type=int, default=30)
    args = parser.parse_args()

    data = json.loads(Path(args.ranked).read_text(encoding="utf-8"))
    benchmark = json.loads(Path(args.benchmark).read_text(encoding="utf-8")) if args.benchmark else None
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = out_dir / "evidence_plots"
    plots_dir.mkdir(exist_ok=True)

    findings = data.get("normalized_findings")
    if findings is None:
        findings = data.get("ranked_findings", [])
        for i, finding in enumerate(findings, start=1):
            finding.setdefault("normalized_rank", i)
            finding.setdefault("disposition", "weak_anomaly")
            finding.setdefault("error_type", finding.get("method", "unknown"))
            finding.setdefault("disposition_reason", "旧版 ranked finding，尚未归一化裁决。")
            finding.setdefault("evidence_examples", finding.get("details", {}).get("evidence_examples", []))

    summary = data.get("assessment_summary") or {
        "highest_observed_tier": "none",
        "counts_by_disposition": dict(Counter(f.get("disposition", "unknown") for f in findings)),
    }
    high = [f for f in findings if f.get("disposition") == "high_confidence_fabrication_compatible_anomaly"]
    weak = [f for f in findings if f.get("disposition") == "weak_anomaly"]
    excluded = [f for f in findings if f.get("disposition") == "not_applicable"]
    highest = summary.get("highest_observed_tier", "none")
    source_data_status = summary.get("source_data_status", "unknown")
    source_data_message = summary.get("source_data_message", "")
    missing_auditable_data = source_data_status in {"missing_auditable_original_data", "no_auditable_numeric_columns"}

    lines = [
        "# 论文数据统计取证报告",
        "",
        "本报告只评估数值和统计层面的异常。`fabrication-compatible anomaly` 表示该统计模式与普通测量生成过程不易相容，需要原始记录、实验流程和作者解释进一步核对；它不是造假证明。",
        "",
        "## 评估摘要",
        "",
        f"- 最高观察等级：{cn_disposition(highest)} (`{highest}`)",
        f"- 高置信度、与统计编造相容的异常：{len(high)}",
        f"- 弱异常线索：{len(weak)}",
        f"- 不适用/已排除命中：{len(excluded)}",
        f"- 原始/source data 状态：`{source_data_status}`",
        f"- 可审计数值列数量：{summary.get('auditable_column_count', 'NA')}",
        f"- 原始统计命中数量：{summary.get('raw_statistical_hit_count', 'NA')}",
        "",
    ]
    if missing_auditable_data:
        lines.append("结论：公开材料中未获得可审计的原始/source data 数值表；因此 stats-only 审计不能判断是否存在统计编造相容异常。")
        if source_data_message:
            lines.append(f"说明：{source_data_message}")
        lines.append("需要先询问用户下一步：是否继续做低置信度的图像/图表数值反推，或停止本轮审计等待原始数据。")
    elif high:
        lines.append("结论：当前证据中发现高置信度、与统计编造相容的异常。")
    else:
        lines.append("结论：基于当前可用证据，未发现高置信度、与统计编造相容的异常。")
    lines.append("")

    lines.extend(["## 高置信度、与统计编造相容的异常", ""])
    for item in high[: args.top]:
        evidence_plot(item, plots_dir)
        lines.extend(finding_block(item))
    if not high:
        lines.append("无。")
        lines.append("")

    lines.extend(["## 弱异常线索", ""])
    for item in weak[: args.top]:
        evidence_plot(item, plots_dir)
        lines.extend(finding_block(item))
    if not weak:
        lines.append("无。")
        lines.append("")

    lines.extend(["## 不适用/已排除命中", ""])
    reason_counts = Counter(f.get("column_type", "unknown") for f in excluded)
    lines.extend(md_table(["排除原因/列类型", "数量"], [[k, v] for k, v in reason_counts.most_common()]))
    lines.append("")
    for item in excluded[: min(args.raw_top, 20)]:
        reason = item.get("eligibility_reason") or item.get("disposition_reason")
        lines.append(f"- `{item.get('source_path')}` / `{item.get('table_name')}` / `{item.get('column')}`：{cn_sentence(reason)}")
    lines.append("")

    context_leads = data.get("context_leads", [])
    if context_leads:
        lines.extend(["## 仅用于定位的上下文线索", ""])
        lines.append("这些条目只用于提示复核优先级，不是统计编造相容异常。")
        for lead in context_leads[:20]:
            lines.append(f"- {lead.get('priority', '')} `{lead.get('kind', '')}`：{lead.get('summary', '')}")
        lines.append("")

    if benchmark:
        lines.extend(["## 统计 Benchmark 结果", ""])
        lines.append(f"- 案例：`{benchmark.get('case_id')}`")
        lines.append(f"- 是否通过：`{benchmark.get('passed')}`")
        lines.append(f"- Exact recovery rate：{benchmark.get('exact_recovery_rate')}")
        lines.append(f"- Exact-or-near recovery rate：{benchmark.get('exact_or_near_recovery_rate')}")
        lines.append(f"- Decoy high-priority failures：{benchmark.get('decoy_high_priority_failures')}")
        lines.append("")

    lines.extend(["## 原始统计附录", ""])
    lines.append("代表性方法输出已合入上方各节；完整归一化 JSON 保留所有原始统计细节和证据字段。")
    lines.append("")
    lines.extend(["## 方法边界", ""])
    lines.append("- 统计异常只是线索，不是学术不端或造假的证明。")
    lines.append("- 小样本、四舍五入、仪器精度、单位换算、阈值处理、离散/有界数据和导出格式都可能造成误报。")
    lines.append("- 本报告为 stats-only：图像重复、错图、图像标签错配不在本轮范围内。")
    lines.append("- 高置信度条目仍需要结合原始实验记录、分析脚本、作者解释和独立复核。")

    report = out_dir / "paper_data_forensics_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
