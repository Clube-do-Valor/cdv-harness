---
paths:
  - "{app_dir}/database/migrations/*.php"
---

# Migrations run with the previous release still serving

A deploy runs the migrations before the new release takes traffic, so every migration lands while the previous release keeps running against it — and keeps running indefinitely when the new release fails its healthcheck and rolls back (a rollback reverts the image, never the schema).

- Additive changes (new table, new nullable column, new index) ship with the code that uses them.
- Renames and drops never ship in the same release as the code that stops using the old shape: first a release that no longer reads it, then the migration that removes it.
- Keep migrations short and free of side effects on other services; a long data backfill is a job or a command, not a migration.
- A migration created on a branch that has not been merged is edited in place or recreated — never altered by a follow-up migration.
- The repository's own deploy facts (how long the old release serves, which workers keep running, its migrations policy document) live in its own rules, next to this one.
