# Architecture

`src/titles.js` builds article paths with `mkSlug` from `lib/helpers/slugify.js`. The CLI in
`bin/cli.js` resolves its commands from a table of helper files, so it never imports them directly.
