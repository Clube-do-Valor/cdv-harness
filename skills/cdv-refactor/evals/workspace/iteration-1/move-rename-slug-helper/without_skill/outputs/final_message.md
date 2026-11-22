`lib/helpers/slugify.js` is now `src/text/slug.js` with `mkSlug` renamed to `toSlug`, and `mkSlugLegacy` and its tests are gone. `npm test` passes: 10 tests, floor 10. I also ran the CLI by hand (`slug` and `truncate`) and both work.

**Commits on `main`**
- `666f4f0 test(truncate): cover the truncate helper`
- `c7c094e refactor(text): move the slug helper to src/text/slug.js and rename mkSlug to toSlug`

**What changed**
- **No shim:** nothing is left at the old path. A grep finds no remaining `mkSlug`, `slugify` or `legacy`.
- **Test rename:** `test/slugify.test.js` is now `test/slug.test.js`, to match the new file name.
- **Updated references:** `src/titles.js`, the command table in `bin/cli.js`, `README.md`, `AGENTS.md` and `docs/architecture.md`.
- **CLI flag removed:** I took out `slugkit slug --legacy` and its code path, since it only existed to call `mkSlugLegacy`.
- **CI filter:** `.github/workflows/ci.yml` only watched `lib/**` and `src/titles.js`. I added `src/text/**`, so changes to the slug helper still trigger CI.

**Test floor.** Deleting the 3 legacy tests left 7 tests, below the floor of 10. `AGENTS.md` says the floor only goes up, so I didn't lower it. Instead I added `test/truncate.test.js` with 3 tests for `truncate`, which had none. That is a small addition beyond what you asked for. If you'd rather lower the floor to 7 and drop that file, it's one commit to revert plus a floor edit.

**Questions for you**
1. `AGENTS.md` told people to put new text helpers next to `slugify.js`, so I pointed that at `src/text/`. `lib/helpers/truncate.js` is still in `lib/helpers/`. Should it move to `src/text/` too? I left it alone as out of scope.
2. Was anything outside this repo still calling `slugkit slug --legacy` or importing `lib/helpers/slugify`? I couldn't check from here.
