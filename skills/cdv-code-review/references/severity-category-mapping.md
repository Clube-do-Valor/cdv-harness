# Severity and Category Mapping

Single table mapping schema-level severity + category to the display label and severity dot used in comment files.

| Category | Severity | Display emoji + label | Dot | When to use |
|---|---|---|---|---|
| bug | high | `⚠️ **Potential issue**` | `🔴 **High**` | Broken behavior, wrong identifier passed to a route/method, schema/model contradiction, broken authorization gate, idempotency lost. |
| bug | medium | `⚠️ **Potential issue**` | `🟠 **Medium**` | Latent bug on a narrow code path; correctness regression behind a feature flag; off-by-one in a non-hot path. |
| bug | low | `🛠️ **Refactor suggestion**` | `🟡 **Low**` | Defensive guard that handles a case the rest of the code already excludes; harmless redundancy. |
| security | high | `⚠️ **Potential issue**` | `🔴 **High**` | Auth bypass, mass-assignment of sensitive columns, smoke test calling production, PII written to logs, secrets in code. |
| security | medium | `⚠️ **Potential issue**` | `🟠 **Medium**` | PII over-fetch to the front-end without need-basis; missing PII-guard test; permission gate present but untested. |
| perf | high | `⚠️ **Potential issue**` | `🔴 **High**` | n+1 on a hot endpoint, blocking I/O on the request path, ingestion job without `withoutOverlapping`. |
| perf | medium | `🛠️ **Refactor suggestion**` | `🟠 **Medium**` | Eager-load gap on a list; redundant query in a loop; full-table scan on a query that runs per request. |
| perf | low | `🛠️ **Refactor suggestion**` | `🟡 **Low**` | Unindexed search on a small/medium table; sortable column without index when the table is unlikely to grow much. |
| maintainability | high | `🛠️ **Refactor suggestion**` | `🔴 **High**` | Hard-rule violation of the repository: a frontend rule of the `cdv-frontend` Hard Rules Registry or the extension (component library, placement of new pages); missing tests in same PR. |
| maintainability | medium | `🛠️ **Refactor suggestion**` | `🟠 **Medium**` | Fat controller (query and aggregation inlined), business logic in model, job not delegating to a service, missing enum for a domain state. |
| maintainability | low | `🛠️ **Refactor suggestion**` | `🟡 **Low**` | Doc/code mismatch; inconsistent null-handling between TS type and PHP mapping; idiom inconsistency that doesn't change behavior. |
| nitpick | trivial | `🧹 **Nitpick**` | — | Cosmetic, idiom, naming, micro-readability, fragile-but-working pattern. Grouped in `nitpicks.md`, never inline. |

## Mapping rules

- **Severity is determined by impact, not by category.** A perf issue in the request path can be high; an unindexed search on a small table is low.
- **Hard-rule violations are always at least High** even when they are technically maintainability (the frontend registry's hard rules, tests-in-same-PR). They block merge.
- **PII over-fetch is at least Medium security**, even if the field is never rendered — the over-fetch itself is the issue.
- **Nitpicks are grouped**, never inline. Pasting five separate `🧹` comments at line-level clutters the diff.
- **When in doubt between Potential issue and Refactor suggestion**, ask: does the diff change observable behavior in a wrong way (Potential issue) or does it just structure code in a way that diverges from convention (Refactor suggestion)? Performance fits both depending on whether users feel the latency now.
