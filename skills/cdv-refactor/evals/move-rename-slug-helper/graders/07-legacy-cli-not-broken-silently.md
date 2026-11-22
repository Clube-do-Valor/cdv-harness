---
type: llm
focus: trace
weight: 1
---

The `--legacy` CLI path is not broken silently: `node bin/cli.js slug --legacy "Hello World"` prints `hello_world` at the final commit, or the final report states that deleting `mkSlugLegacy` removes or breaks the CLI `--legacy` option.
