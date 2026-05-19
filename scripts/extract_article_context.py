#!/usr/bin/env python
"""Extract article claims, figure captions, notices, and source-data links."""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 paper-data-forensics"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def read_input(args: argparse.Namespace) -> tuple[str, str, str]:
    if args.article_text:
        path = Path(args.article_text)
        raw = path.read_text(encoding="utf-8", errors="replace")
        return raw, raw, str(path)
    if args.article_html:
        path = Path(args.article_html)
        raw = path.read_text(encoding="utf-8", errors="replace")
        return html_to_text(raw), raw, str(path)
    if args.article_url:
        raw = fetch_url(args.article_url)
        return html_to_text(raw), raw, args.article_url
    raise SystemExit("Provide one of --article-url, --article-html, or --article-text")


def html_to_text(raw: str) -> str:
    parser = TextHTMLParser()
    parser.feed(raw)
    return "\n".join(parser.parts)


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_title(text: str) -> str:
    for line in text.splitlines():
        line = norm_space(line)
        if line and len(line) > 20 and not line.lower().startswith(("advertisement", "skip to")):
            return line
    return ""


def extract_abstract(text: str) -> str:
    match = re.search(r"\bAbstract\b\s*(.+?)(?:\n\s*(?:Data availability|References|Fig\. 1|Introduction|Author information)\b)", text, re.I | re.S)
    return norm_space(match.group(1)) if match else ""


def extract_notices(text: str) -> list[dict[str, str]]:
    notices = []
    patterns = [
        (r"(\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\s+Editor's note:.+?)(?=\n\s*(?:An Author Correction|This article|##|Abstract|Fig\.|$))", "editor_note"),
        (r"(An Author Correction to this article was published on \d{1,2}\s+[A-Z][a-z]+\s+\d{4})", "author_correction_link"),
        (r"(In the version of this article initially published,.+?The figures have been corrected.+?)(?=\n|$)", "author_correction_text"),
    ]
    for pattern, kind in patterns:
        for match in re.finditer(pattern, text, re.I | re.S):
            notices.append({"kind": kind, "text": norm_space(match.group(1))})
    return notices


def extract_captions(text: str) -> list[dict[str, Any]]:
    caption_re = re.compile(
        r"((?:Extended Data Fig\.|Fig\.)\s*\d+[^\n]*?)(?=\n\s*(?:Image|The alternative text|[a-z],|[A-Z][a-z]+)|$)(.*?)(?=\n\s*(?:Extended Data Fig\.|Fig\.)\s*\d+|Data availability|References|Methods|Acknowledgements|Supplementary information|$)",
        re.S,
    )
    captions = []
    for match in caption_re.finditer(text):
        heading = norm_space(match.group(1))
        body = norm_space(match.group(2))
        fig_match = re.search(r"(Extended Data Fig\.|Fig\.)\s*(\d+)", heading)
        if not fig_match:
            continue
        fig_type = "extended_data" if fig_match.group(1).startswith("Extended") else "main"
        figure_id = ("ED Fig." if fig_type == "extended_data" else "Fig.") + fig_match.group(2)
        panels = sorted(set(re.findall(r"\b([a-z])\s*,", body)))
        captions.append({"figure_id": figure_id, "figure_type": fig_type, "heading": heading, "caption": body, "panels": panels})
    return captions


def extract_data_availability(text: str) -> str:
    match = re.search(r"\bData availability\b\s*(.+?)(?:\n\s*(?:Change history|References|Acknowledgements|Author information)\b)", text, re.I | re.S)
    return norm_space(match.group(1)) if match else ""


def source_links_from_html(raw_html: str) -> list[str]:
    urls = re.findall(r"https?://[^\"'<>\s]+(?:xlsx|xls|pdf)", raw_html, re.I)
    urls += re.findall(r"static-content\.springer\.com/[^\"'<>\s]+(?:xlsx|xls|pdf)", raw_html, re.I)
    return sorted(set(html.unescape(u) for u in urls))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--article-url")
    parser.add_argument("--extra-url", action="append", default=[], help="Additional article/correction URL to merge into context")
    parser.add_argument("--article-html")
    parser.add_argument("--article-text")
    parser.add_argument("--raw-html")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    text, raw_main, source = read_input(args)
    extra_sources = []
    raw_extra = ""
    for url in args.extra_url:
        raw = fetch_url(url)
        text += "\n" + html_to_text(raw)
        raw_extra += "\n" + raw
        extra_sources.append(url)
    raw_html = Path(args.raw_html).read_text(encoding="utf-8", errors="replace") if args.raw_html else ""
    result = {
        "source": source,
        "extra_sources": extra_sources,
        "title": extract_title(text),
        "abstract": extract_abstract(text),
        "notices": extract_notices(text),
        "figures": extract_captions(text),
        "data_availability": extract_data_availability(text),
        "source_links": source_links_from_html(raw_html or raw_main + raw_extra),
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote article context with {len(result['figures'])} figures to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
