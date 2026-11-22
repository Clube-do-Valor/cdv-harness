# Notes for coding agents

- A new text helper goes next to `lib/helpers/slugify.js`, with its tests in `test/` (see `test/slugify.test.js`).
- Every URL slug comes from `mkSlug`; never build one by hand.
- `npm test` must pass, floor included. The floor in `test-floor.json` only goes up.
