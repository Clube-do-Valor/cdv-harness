# Setting up the token, the settings and the cache

## The token

The client talks to the public REST API with one token: an internal integration's token (created by a workspace owner in the Notion developer portal, shared with the team by whoever owns it) or a personal access token. The client does not care which; it reads whichever is on the machine, in this order:

1. `$NOTION_API_TOKEN` (the variable the official `ntn` CLI also reads);
2. the keyring: `secret-tool lookup service notion-api`;
3. `~/.config/notion/credentials`, mode 600, the first non-comment line. A file that group or others can read still works, and the client prints one warning line naming it and the `chmod 600` that fixes it.

Store it once, in a terminal (not through the chat: the prompt needs a real TTY), with `notion auth login`. It reads the token at a hidden prompt, checks it with `GET /v1/users/me`, and stores it in the keyring, or in the credentials file with mode 600 when there is no keyring. `notion auth status` says where the token came from and whose it is; `notion auth logout` removes the keyring entry. Never paste a token in a chat, never commit it, never put it in a profile or an `.env` of a repository. The client never prints it and sends it only to `api.notion.com`.

## What the integration needs

- **Capabilities** (set on the integration by its owner): read, update and insert content; read and insert comments; user information with e-mail addresses (without it, `whoami` and `users find` only know the people seen in rows read).
- **Access:** the pages and data sources it works on must be connected to it (page menu → Connections → the integration); children inherit the connection.

`notion doctor` prints one line per item: the token's owner kind (workspace integration or personal token), each capability (the read ones probed; the write ones proven by `notion doctor --write-check <data source>`, which creates a card whose title starts with the test marker, writes a property, a callout, a table and a toggle, reads the stored blocks back (a construct saved as plain text fails), comments, and trashes it; when the create ends in doubt it looks for the card by its title, which holds the time to the second, and trashes it, or prints that title to look for by hand, and exits `1`), and each connected data source with its title and key prefix.

## Settings: `~/.config/cdv-notion/config.json`

```json
{
  "me": "you@example.com",
  "stamp_comments": "on",
  "test_marker": "<title prefix of the write-check card>"
}
```

- `me` — the e-mail of the person this machine acts for (default: `git config user.email`). It resolves `me` in `--set` and `--where`, and signs comments.
- `stamp_comments` — `on` (default) shows a comment written with a workspace integration token under the name of `me`; `off` shows it as the integration. A personal token always shows its owner.
- `test_marker` — the title prefix of the card `doctor --write-check` creates; a repository can pass `--marker` instead.

## The cache: `~/.cache/cdv-notion/`

The list of connected data sources with their key prefixes, each schema, people seen in rows and the kind of each id. It saves calls and is safe to delete: the next command rebuilds what it needs and answers the same. Sessions that write at the same time lose nothing: a file that is read, merged and written (the people, the kinds, the list) is held under a lock for that (a `.<name>.lock` file beside it, where the system has `flock`). A schema is read again on its own, at most once per command for each data source, when a cached copy turns out to be old: a `--set`, `--where`, `--order`, `--select` or `--group-by` names a property or an option the copy does not have, Notion answers 400 to something built from it (a property renamed or deleted since, in `search`, `query`, a ticket key, `create` or `update`), or a row does not hold a column the output reads. The step is then built again and, when it comes out different, run once more; a write answered 400 changed nothing. A name that is still unknown is refused as any unknown name is (exit `2`). `fetch <data source>` and the write check always read the schema from the API. A text property added since the copy was made is not searched until the copy is read again: `notion fetch <data source>` does it.
