# Company Extraction Agent — Memory

## Lessons learned
- **#parent-rollup** Products/brands map to listed parents only when supported; corporate relationships are time-dependent.
- **#no-guess** A doubtful ticker is an empty string, not a lookalike.
- **#dedupe** Repeated summaries do not create additional companies. Deduplicate a parent even if several brands/classes appear.
- **#event-owner** Distinguish an earnings reporter from a peer reacting to the release.
- **#not-a-position** A resolved entity is review context, not a holding or approved trade.
