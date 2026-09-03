# Company Extraction Agent — Memory

## Lessons learned
- **#parent-rollup** Products and brands map to the listed parent (YouTube TV → GOOGL, ESPN → DIS); ETFs and indexes are not companies.
- **#no-guess** An unsure ticker is an empty string, never a lookalike (MRVL is not MRVA).
- **#dedupe** One row per company even when several summaries mention it.

## Log
<!-- template: ## YYYY-MM-DD #tag — one short line per lesson -->
