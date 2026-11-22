The slug helper now lives at `src/text/slug.js` and is called `toSlug`. `mkSlugLegacy` and its tests are gone, and there's no shim at the old path. `npm test` passes at 10 tests, with the floor still at 10. I ran the stale-mention check from the skill's `docs_follow_code.py` against the last three commits. It found no mention of `mkSlug`, `mkSlugLegacy` or the old path in the docs. There was no state folder or gate set up in this repo, so I kept to four small commits.

**Commits, in order**
1. `7c12499` adds `test/cli.test.js`, 3 tests recording the CLI's current behaviour. The CLI loads helpers from path and function-name strings, so a grep for `mkSlug` doesn't see it. These tests also keep the count at the floor after the deletion.
2. `d277e41` deletes `mkSlugLegacy`, `test/legacy.test.js` (3 tests) and the CLI's `--legacy` flag.
3. `41e09f6` moves the file byte for byte, and `test/slugify.test.js` becomes `test/slug.test.js`. Paths are updated in `src/titles.js`, the CLI table, the tests, README, `docs/architecture.md` and `AGENTS.md`.
4. `45072bc` renames `mkSlug` to `toSlug` in every caller, including the CLI's `fn` string and the docs.

**Beyond what you asked**
- **CI trigger:** I changed the filter in `.github/workflows/ci.yml` from `src/titles.js` to `src/**`. Without that, a PR that only touches `src/text/slug.js` wouldn't run CI.
- **Added tests:** `test-floor.json` says the floor only goes up. Deleting the 3 legacy tests would have left 7 tests against a floor of 10. I added the 3 CLI tests instead of lowering the floor.
- **CLI output:** `slug`, `truncate` and the unknown-command path give the same output as before (checked before and after). `slugkit slug Crème Brûlée` still prints `creme-brulee`.

**Questions for you**
1. **Removed `--legacy`:** The CLI's `--legacy` flag was `mkSlugLegacy`'s only caller, so I removed it. Is that what you meant? If anything still calls `slugkit slug --legacy`, `--legacy` is now treated as part of the text and would end up in the slug. Check for scripts that use the flag before releasing.
2. **Floor:** Do you want to lower `test-floor.json` now that the legacy tests are gone? I left it alone because the rule says it only goes up, and the CLI tests are real coverage anyway.
3. **`truncate`:** It is still in `lib/helpers/truncate.js`, and `AGENTS.md` now says new text helpers go next to `src/text/slug.js`. I left `truncate` where it is because you asked only for the slug helper. Should it move to `src/text/` too?
