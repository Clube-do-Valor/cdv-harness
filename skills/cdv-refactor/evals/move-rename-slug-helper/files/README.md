# slugkit

Slugs and titles for the article pages.

- `lib/helpers/slugify.js` - `mkSlug(title, separator)`, the slug of every article URL.
- `lib/helpers/truncate.js` - `truncate(text, max)`.
- `src/titles.js` - `articlePath` and `cardTitle`, built on the helpers.
- `bin/cli.js` - `slugkit slug <text>`, `slugkit slug --legacy <text>`, `slugkit truncate <text> <max>`.

`npm test` runs the suite and the test floor (`test-floor.json`).
