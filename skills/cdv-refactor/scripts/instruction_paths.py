#!/usr/bin/env python3
"""The instruction files name only paths that exist, and the list of exceptions only shrinks.

    instruction_paths.py [--folder <state folder>] [--instructions <path|folder|glob> ...]
                         [--resolve-from <dir> ...] [--skip <prefix> ...] [--allow <file>]
                         [--base [<rev>]] [--include-vendored] [--list] [--write-allowlist]

An agent that reads "see `app/Services/OldThing.php`" opens a file that is not there and learns to
distrust the rest. This reads the instruction files and fails when one names a repository path that
does not exist, except for the dangling references in the allow file, which may only shrink: a listed
reference that no longer dangles fails with "remove this entry", and a new dangling reference fails
until it is fixed.

WHAT IS AN INSTRUCTION FILE AND WHERE PATHS RESOLVE - never constants, always one of:

  arguments   `--instructions` (repeatable): a file, a folder (every `.md` and `.mdc` below it) or a glob
              (`*` within a folder, `**` across folders), relative to the repository root.
              `--resolve-from` (repeatable): a folder, relative to the root, that a path may also be
              written relative to (`app/`, `src/resources/js/`). `--skip`: a prefix to leave out.
  the folder  `instruction-paths.json` in the state folder, `{"instructions": [...], "resolve_from":
              [...], "skip": [...]}`; arguments given on the command line replace the lists of the file.
              The allow file is `instruction-paths.allow` there, unless `--allow` says otherwise.

Without either, there is nothing to read: usage error.

WHAT IS A PATH AND WHAT IS PROSE
  A token is checked only when it is written like a path in one of these places:
    - an inline code span `like/this.php` or a word inside a fenced code block;
    - a Markdown link target [text](docs/x.md);
    - a bare word in prose that starts with a repository root folder and a slash.
  and only when ALL hold: it contains a slash; its first folder is one that exists in the repository (a root
  folder, a folder of a `--resolve-from` directory) or it starts with ./ or ../; it has no placeholder or shell
  syntax (<x> {x} $x [x] | = ( ) quotes, ..., ://, @/ aliases, absolute or ~ paths).
  Bare file names in code spans (`agent.md`, `routes.php`) count when they have a known extension and no file of
  that name exists anywhere in the repository. `path:12`, `path#L3`, `path::method` are checked as `path`. A `*`
  glob is checked by its static directory. Paths ignored by git (vendor, node_modules, generated folders) are
  treated as existing. A path resolves from the repository root, from each `--resolve-from` directory, from the
  folder of the file that names it, or from the skill folder of a file under `.claude/skills/<name>/`. A path
  whose first folder is not a root folder ("types/user.ts") also resolves when some file or folder of the
  repository ends with it, because guides write such paths relative to the module they describe.
  The folders the harness lock pins (`.claude/harness.lock`, "paths": copies of the core, changed in the core)
  are skipped unless `--include-vendored`.
  What this cannot see: a path written in prose without a root folder, a path built from parts, a stale
  statement that names a path that happens to exist.

ALLOW FILE
  One `<instruction file><TAB><token>` per line, sorted; `#` lines are comments. A number inside the file it caps
  proves nothing, so the list can only shrink, and that is read from git, not from the file:
    - HISTORY: in every commit of <base>..HEAD (all parents, a merge against the union of its parents) the
      entries must be a subset of the entries of the commit's parent(s). The one exception is the commit that
      CREATES the file (the first one of the range, when it did not exist at the base): put every entry in it.
      Re-adding an entry an earlier commit removed is an addition too; add, remove, add fails at the second add.
    - WORKING TREE: the entries on disk must be a subset of the entries of HEAD.
  A reference that dangles and is not listed fails as NEW: fix the reference. `--write-allowlist` creates the
  allow file listing every current dangling reference, for the commit that creates it (it refuses to overwrite
  one that exists). Without `--base` (bare: from `state.json`) an allow file with entries cannot be judged from
  git: the run is PARTIAL.

Last line: `instruction_paths check: PASS|FAIL|PARTIAL - ...`. Exit 0 no new dangling reference, no stale entry
and the list did not grow, 1 a new dangling reference, a stale entry or a list that grew, 2 usage, 3 git
failed, 4 partial: nothing failed but no instruction file matched, or the history of an allow file with
entries was not read.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

TOOL = "instruction_paths"
DASH = "\u2014"
FROM_STATE = "@state"
KNOWN_EXTENSIONS = ("md", "mdc", "yml", "yaml", "json", "toml", "sh", "neon", "php", "vue", "ts", "tsx", "js", "jsx", "py", "rb", "go", "rs", "xml", "txt", "css")

CODE_SPAN = re.compile(r"`([^`\n]+)`")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
PLACEHOLDER = re.compile(r"[<>{}$\[\]|=()\"'\\]|\.\.\.|\u2026|://|^@|^~|^/|^%|^-")
LINE_SUFFIX = re.compile(r"(?::\d+(?:[-:]\d+)*|#L?\d+(?:-L?\d+)?|::[\w$]+)+$")


class Usage(Exception):
    pass


class Environment(Exception):
    pass


def verdict(mode, status, text):
    print(f"{TOOL} {mode}: {status} {DASH} {text}")


def git_run(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def git_lines(root, *args):
    result = git_run(root, *args)
    if result.returncode != 0:
        raise Environment(f"git {' '.join(args[:3])} failed: {result.stderr.decode(errors='replace').strip()[:200]}")
    return [line for line in result.stdout.decode(errors="replace").split("\0") if line]


def git_text(root, *args):
    result = git_run(root, *args)
    return result.stdout.decode(errors="replace") if result.returncode == 0 else None


def glob_to_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def locked_prefixes(root):
    """The folders the harness lock pins (.claude/harness.lock, "paths"): copies of the core, changed in the core."""
    try:
        with open(os.path.join(root, ".claude/harness.lock"), encoding="utf-8") as handle:
            paths = json.load(handle).get("paths", [])
    except (OSError, ValueError, AttributeError):
        return ()
    if not isinstance(paths, list):
        return ()
    return tuple(p.strip("/") + "/" for p in paths if isinstance(p, str) and p.strip("/"))


def matcher(entry):
    """A function path -> bool for an instruction entry: a glob, or a path standing for itself and everything under it."""
    if re.search(r"[*?]", entry):
        regex = glob_to_regex(entry)
        return lambda path: bool(regex.match(path))
    plain = entry.rstrip("/")
    return lambda path: path == plain or path.startswith(plain + "/")


class Repository:
    """The files and folders that exist: tracked files plus untracked files git does not ignore."""

    def __init__(self, root, instructions, resolve_from, skip):
        self.root = str(root)
        self.vendored = tuple(skip) + locked_prefixes(root)
        self.matchers = [matcher(entry) for entry in instructions]
        self.resolve_from = [r.strip("/") for r in resolve_from if r.strip("/")]
        files = set(git_lines(root, "ls-files", "-z")) | set(git_lines(root, "ls-files", "-z", "--others", "--exclude-standard"))
        self.files = {f for f in files if os.path.exists(os.path.join(root, f))}
        self.dirs = set()
        for path in self.files:
            parts = path.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.basenames = {os.path.basename(f) for f in self.files}
        self.suffixes = set()
        for path in self.files | self.dirs:
            parts = path.split("/")
            for i in range(1, len(parts)):
                self.suffixes.add("/".join(parts[i:]))
        self.root_folders = {p.split("/")[0] for p in self.files if "/" in p}
        self.nested_folders = set()
        for base in self.resolve_from:
            depth = base.count("/") + 1
            self.nested_folders |= {p.split("/")[depth] for p in self.files if p.startswith(base + "/") and p.count("/") > depth}
        self._ignored_cache = {}

    def exists(self, path):
        path = path.rstrip("/")
        return path in self.files or path in self.dirs

    def is_ignored(self, path):
        if path not in self._ignored_cache:
            self._ignored_cache[path] = git_run(self.root, "check-ignore", "-q", "--", path).returncode == 0
        return self._ignored_cache[path]

    def instruction_files(self, include_vendored):
        found = []
        for path in sorted(self.files):
            if not path.endswith((".md", ".mdc")) or not any(m(path) for m in self.matchers):
                continue
            if include_vendored or not path.startswith(self.vendored):
                found.append(path)
        return found


def words(text):
    """Whitespace-separated words with the punctuation that wraps them removed."""
    return [w for w in (word.strip("()[]{}\"',;") for word in text.split()) if w]


def candidates_from_line(line, in_fence, repo):
    """Returns (token, allowed first folders, where) for the path-like tokens a line may contain."""
    with_nested = repo.root_folders | repo.nested_folders
    seen = []
    if in_fence:
        for word in words(line):
            seen.append((word, with_nested, "fence"))
        return seen
    for span in CODE_SPAN.findall(line):
        for word in words(span):
            seen.append((word, with_nested, "span"))
    for target in LINK_TARGET.findall(line):
        if not re.match(r"^[a-z][a-z0-9+.-]*:", target) and not target.startswith("#"):
            seen.append((target.split("#")[0], with_nested, "link"))
    outside = CODE_SPAN.sub(" ", LINK_TARGET.sub(" ", line))
    for word in words(outside):
        seen.append((word, repo.root_folders, "prose"))
    return seen


def normalise(token):
    token = token.strip().rstrip(".,;:!?")
    token = LINE_SUFFIX.sub("", token)
    return token.rstrip(".,;:")


def skill_folder(doc_path):
    """The skill a document describes: its own folder under .claude/skills."""
    parts = doc_path.split("/")
    if doc_path.startswith(".claude/skills/") and len(parts) > 3:
        return "/".join(parts[:3])
    return None


def resolves(repo, token, doc_dir, skill=None):
    """True when the token names something that exists, or something git ignores (generated)."""
    static = token
    if "*" in token:
        static = token.split("*")[0]
        static = static[: static.rfind("/")] if "/" in static else ""
        if static == "":
            return True
    if "/" in static and static.split("/")[0] not in repo.root_folders and static.rstrip("/") in repo.suffixes:
        return True  # written relative to some folder of the module being described ("types/user.ts")
    bases = [""] + [r + "/" for r in repo.resolve_from]
    if doc_dir:
        bases.append(doc_dir.rstrip("/") + "/")
    if skill:
        bases.append(skill.rstrip("/") + "/")
    for base in bases:
        candidate = os.path.normpath(base + static) if token.startswith(("./", "../")) or base in (doc_dir, skill) else base + static
        candidate = candidate.rstrip("/")
        if candidate and (repo.exists(candidate) or repo.is_ignored(candidate)):
            return True
    return False


def dangling_references(repo, include_vendored):
    """Returns {(instruction file, token): [line numbers]} for the references that do not resolve."""
    found = {}
    for path in repo.instruction_files(include_vendored):
        doc_dir = os.path.dirname(path)
        skill = skill_folder(path)
        in_fence = False
        with open(os.path.join(repo.root, path), encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if line.lstrip().startswith(("```", "~~~")):
                    in_fence = not in_fence
                    continue
                for raw, first_folders, where in candidates_from_line(line, in_fence, repo):
                    token = normalise(raw)
                    if not token or PLACEHOLDER.search(token):
                        continue
                    if "/" in token:
                        first = token.split("/")[0]
                        if not (token.startswith(("./", "../")) or first in first_folders):
                            continue
                        if first.startswith(".") and first not in (".claude", ".github", ".", ".."):
                            continue
                    else:
                        extension = token.rsplit(".", 1)[-1] if "." in token.strip(".") else ""
                        if where != "span" or extension not in KNOWN_EXTENSIONS or "*" in token:
                            continue
                        if token in repo.basenames or repo.is_ignored(token) or token.startswith("."):
                            continue
                        found.setdefault((path, token), []).append(number)
                        continue
                    if not resolves(repo, token, doc_dir, skill):
                        found.setdefault((path, token), []).append(number)
    return found


def parse_entries(text, where, strict):
    """The (instruction file, token) pairs of an allow file; comments and blank lines are ignored."""
    entries = set()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "\t" not in line:
            if strict:
                raise Usage(f"{where}: line without a TAB between file and token: {line!r}")
            continue
        file, token = line.split("\t", 1)
        entries.add((file, token))
    return entries


def load_allow(allow_path):
    if not allow_path.is_file():
        return set()
    return parse_entries(allow_path.read_text(encoding="utf-8"), str(allow_path), True)


def render_allow(entries):
    header = (
        "# Dangling references in the instruction files today. The list may only shrink:\n"
        "# fix the reference and delete its line. Format: <instruction file><TAB><token>, sorted.\n"
        "# Growth is read from git (instruction_paths.py --base): no commit may add a line after the one that created this file.\n"
    )
    return header + "".join("%s\t%s\n" % entry for entry in sorted(entries))


def history_problems(root, allow_path, base):
    """Entries added to the allow file by a commit of base..HEAD (other than the one that created it), or by the
    working tree on top of HEAD. Returns a list of messages."""
    relative = os.path.relpath(allow_path.resolve(), Path(root).resolve())
    if relative.startswith(".."):
        raise Usage(f"the allow file {allow_path} is outside the repository: its history cannot be read, so the list could grow unseen")
    if git_text(root, "rev-parse", "--verify", "-q", base + "^{commit}") is None:
        raise Usage(f"{base} is not a commit of {root}")
    created = git_text(root, "show", f"{base}:{relative}") is not None
    listing = git_text(root, "log", "--reverse", "--topo-order", "--full-history", "--format=%H %P", f"{base}..HEAD", "--", relative)
    if listing is None:
        raise Environment(f"git log {base}..HEAD failed")
    problems = []
    for row in listing.splitlines():
        commit, *parents = row.split()
        after = git_text(root, "show", f"{commit}:{relative}")
        if after is None:
            continue  # the file was deleted here: nothing was added
        before_texts = [git_text(root, "show", f"{parent}:{relative}") for parent in parents]
        before = set().union(*[parse_entries(text, "", False) for text in before_texts if text is not None])
        if all(text is None for text in before_texts) and not created:
            created = True  # the commit that creates the file lists whatever dangles today
            continue
        added = parse_entries(after, "", False) - before
        if added:
            subject = (git_text(root, "log", "-1", "--format=%h %s", commit) or commit).strip()
            problems.append((subject, sorted(added)))
    messages = []
    for subject, added in problems:
        plural = "y" if len(added) == 1 else "ies"
        listed = "; ".join("%s -> `%s`" % entry for entry in added[:5]) + ("; ..." if len(added) > 5 else "")
        messages.append(f"GREW   commit {subject} added {len(added)} entr{plural} to the allow file: {listed}")
    if allow_path.is_file():
        on_disk = parse_entries(allow_path.read_text(encoding="utf-8"), str(allow_path), False)
        head_text = git_text(root, "show", f"HEAD:{relative}")
        if head_text is not None or created:
            added = sorted(on_disk - (parse_entries(head_text, "", False) if head_text is not None else set()))
            if added:
                plural = "y" if len(added) == 1 else "ies"
                listed = "; ".join("%s -> `%s`" % entry for entry in added[:5])
                messages.append(f"GREW   the working tree adds {len(added)} entr{plural} to the allow file that HEAD does not have: {listed}")
    return messages


def base_from_state(folder):
    path = folder / "state.json" if folder else None
    if not path or not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    running = [p for p in state.get("phases", []) if p.get("status") == "running" and p.get("start")]
    return (running[-1]["start"] if running else None) or state.get("base")


def configuration(folder):
    if not folder:
        return {}
    path = folder / "instruction-paths.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise Usage(f"{path} is not valid JSON: {error}")
    if not isinstance(data, dict):
        raise Usage(f"{path} must be a JSON object")
    for key in ("instructions", "resolve_from", "skip"):
        if not isinstance(data.get(key, []), list) or not all(isinstance(v, str) for v in data.get(key, [])):
            raise Usage(f'{path}: "{key}" must be a list of strings')
    return data


def check(root, repo, allow_path, include_vendored, list_all, base):
    dangling = dangling_references(repo, include_vendored)
    allowed = load_allow(allow_path) if allow_path else set()
    current = set(dangling)
    read = len(repo.instruction_files(include_vendored))

    if list_all:
        for (path, token), lines in sorted(dangling.items()):
            print("  %s:%s  %s" % (path, ",".join(str(n) for n in lines[:5]), token))

    new = sorted(current - allowed)
    stale = sorted(allowed - current)
    problems = 0
    for path, token in new:
        problems += 1
        print(f"NEW    {path}:{dangling[(path, token)][0]}  `{token}` does not exist: fix the reference (do not list it)")
    for path, token in stale:
        problems += 1
        print(f"STALE  {path}  `{token}` no longer dangles: remove this line from {allow_path}")
    grew = history_problems(root, allow_path, base) if (base and allow_path and (allowed or allow_path.is_file())) else []
    for message in grew:
        problems += 1
        print(message)
    if grew:
        print("       The list only shrinks: fix the dangling reference instead of listing it.")
    unjudged = bool(allowed) and not base
    if unjudged:
        print("NOTICE the history of the allow file was not read (no --base): the list could have grown")
    summary = f"{len(current)} dangling reference(s) in {read} instruction file(s) read, {len(allowed & current)} allow-listed"
    if problems:
        verdict("check", "FAIL", f"{problems} problem(s): {summary}")
        return 1
    if read == 0:
        verdict("check", "PARTIAL", "no instruction file matched: nothing was read")
        return 4
    if unjudged:
        verdict("check", "PARTIAL", f"the history of the allow file was not read ({summary})")
        return 4
    verdict("check", "PASS", summary + (f", history since {base[:12]}" if base and allow_path else ""))
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def main(argv=None):
    parser = Parser(description="The instruction files name only paths that exist.")
    parser.add_argument("--folder", help="the refactor's state folder (instruction-paths.json, the allow file, state.json)")
    parser.add_argument("--instructions", action="append", help="an instruction file, folder or glob (repeatable)")
    parser.add_argument("--resolve-from", action="append", help="a folder a path may be written relative to (repeatable)")
    parser.add_argument("--skip", action="append", help="a prefix of files to leave out (repeatable)")
    parser.add_argument("--allow", help="the allow file; default: <folder>/instruction-paths.allow")
    parser.add_argument("--base", nargs="?", const=FROM_STATE, help="the revision the allow file's history is read from; bare: from state.json")
    parser.add_argument("--include-vendored", action="store_true")
    parser.add_argument("--list", action="store_true", help="print every dangling reference with file:line")
    parser.add_argument("--write-allowlist", action="store_true", help="create the allow file listing every current dangling reference")
    mode = "check"
    try:
        args = parser.parse_args(argv)
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            raise Environment("not inside a git repository")
        root = Path(top.stdout.strip())
        folder = Path(args.folder) if args.folder else None
        config = configuration(folder)
        instructions = args.instructions if args.instructions is not None else config.get("instructions", [])
        resolve_from = args.resolve_from if args.resolve_from is not None else config.get("resolve_from", [])
        skip = args.skip if args.skip is not None else config.get("skip", [])
        if not instructions:
            raise Usage("no instruction file named: pass --instructions, or list them in instruction-paths.json of the state folder")
        allow = Path(args.allow) if args.allow else (folder / "instruction-paths.allow" if folder else None)
        base = None
        if args.base is not None:
            base = base_from_state(folder) if args.base == FROM_STATE else args.base
            if not base:
                raise Usage("--base needs a revision, or a base in state.json")
        repo = Repository(root, instructions, resolve_from, skip)
        if args.write_allowlist:
            mode = "write-allowlist"
            if not allow:
                raise Usage("--write-allowlist needs --allow or --folder")
            if allow.exists():
                raise Usage(f"{allow} exists: the list only shrinks, edit it by hand")
            entries = set(dangling_references(repo, args.include_vendored))
            allow.write_text(render_allow(entries), encoding="utf-8")
            verdict(mode, "PASS", f"{len(entries)} dangling reference(s) listed in {allow}")
            return 0
        return check(root, repo, allow, args.include_vendored, args.list, base)
    except SystemExit as error:  # --help
        return error.code or 0
    except Usage as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        verdict(mode, "FAIL", f"usage: {error}")
        return 2
    except Environment as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        verdict(mode, "FAIL", f"environment: {error}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
