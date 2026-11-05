# Changelog

## Unreleased

- `sync` also stages `.claude/harness/profile.yaml` with `git add -f`, so a repository that ignores `.claude/` commits its profile with the first sync. `profile.local.yaml` stays out of git.

## v0.2.1

- `tlc-spec-lean` is installed per user only (`"vendor": false` in `third-party.json`): `sync` no longer copies it into repositories, and `sync --user` still installs it.

## v0.2.0

- Three third-party skills copied from the Tech Leads Club catalog: `tlc-spec-lean`, `create-adr` and `modular-design-principles` (CC-BY-4.0, see `THIRD_PARTY.md`). They are vendored into consumers like the house skills and installed per user by `sync --user`.
- `bin/harness third-party` copies new upstream versions listed in `third-party.json`; `--check` only reports them. A weekly workflow runs it and opens a PR.
- `sync` vendors every skill under `skills/`, not only `cdv-*`.

## v0.1.0

First release.

- 17 house skills: `cdv-plan-feature`, `cdv-finalize`, `cdv-open-pr`, `cdv-code-review`, `cdv-pr-review`, `cdv-apply-review`, `cdv-debug`, `cdv-interactive-qa`, `cdv-notion-ticket`, `cdv-grilling`, `cdv-grill-me`, `cdv-research-round`, `cdv-frontend`, `cdv-factory-small-feature`, `cdv-factory-finalize`, `cdv-handoff`, `cdv-flows`. Each reads the repository profile in its step 0 and its optional extension.
- House rules `cdv-config-env`, `cdv-tests` and `cdv-migrations`, the house instructions block and the core deny list (production-affecting command families, inline PHP, and Edit on the vendored paths).
- `profile.schema.yaml`: the variables a consumer declares.
- `bin/harness` with `sync`, `sync --user`, `verify`, `propose`, `catalog`, `release`, `lint` and `scan`; `bin/verify.sh` as the offline CI gate.
- Generated `CATALOG.md` and `registry.json`.
