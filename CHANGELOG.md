# Changelog

## v0.1.0

First release.

- 17 house skills: `cdv-plan-feature`, `cdv-finalize`, `cdv-open-pr`, `cdv-code-review`, `cdv-pr-review`, `cdv-apply-review`, `cdv-debug`, `cdv-interactive-qa`, `cdv-notion-ticket`, `cdv-grilling`, `cdv-grill-me`, `cdv-research-round`, `cdv-frontend`, `cdv-factory-small-feature`, `cdv-factory-finalize`, `cdv-handoff`, `cdv-flows`. Each reads the repository profile in its step 0 and its optional extension.
- House rules `cdv-config-env`, `cdv-tests` and `cdv-migrations`, the house instructions block and the core deny list (production-affecting command families, inline PHP, and Edit on the vendored paths).
- `profile.schema.yaml`: the variables a consumer declares.
- `bin/harness` with `sync`, `sync --user`, `verify`, `propose`, `catalog`, `release`, `lint` and `scan`; `bin/verify.sh` as the offline CI gate.
- Generated `CATALOG.md` and `registry.json`.
