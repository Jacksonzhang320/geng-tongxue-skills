# Contributing

Pull requests are welcome.

## Scope

- Add or improve detection methods in `scripts/`.
- Update `SKILL.md` when the workflow, reporting rules, or invocation pattern changes.
- Keep examples small and reproducible.
- Prefer conservative wording: statistical anomalies are leads for review, not proof of misconduct.

## Do Not Commit

- Paper source data, downloaded PDFs, Excel workbooks, or supplementary files.
- Generated reports, evidence plots, logs, checkpoints, or intermediate outputs.
- API keys, tokens, private paths, or credentials.

The `.gitignore` is intentionally broad to keep the repository focused on the skill code and instructions.

## Review Expectations

- New checks should explain when they are applicable and when they should be downweighted or excluded.
- Findings should include reproducible evidence such as file path, sheet/table, column, row/cell, raw value, and method.
- Reports should include limitations and avoid allegations.
