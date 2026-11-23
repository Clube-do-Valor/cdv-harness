"""Shared helpers of the cdv-harness hooks.

A PreToolUse hook reads the tool call as JSON on stdin, exits 0 to let it run and 2 to block it;
what it prints on stderr reaches the model as the reason. A PostToolUse hook (card-check) runs after
the call, so its exit 2 cannot undo it: the stderr reaches the model beside the tool result. Every
hook fails open: a missing profile, input that is not JSON or any unexpected error lets the call
run, because a broken hook must never stop a session.

Vendored by `harness sync` to `.claude/harness/hooks/`, beside the repository profile one level
up (`.claude/harness/profile.yaml`), and by `harness sync --user` to `<config dir>/harness/hooks/`,
where there is no profile. Standard library only.
"""

import json
import re
import shlex
import sys
from pathlib import Path

ALLOW = 0
BLOCK = 2


def harness_dir():
    return Path(__file__).resolve().parent.parent


def repo_root():
    return harness_dir().parent.parent


def _scalar(text):
    text = text.strip()
    if not text or text.startswith("#"):
        return None
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        return text[1:end] if end > 0 else text[1:]
    return re.split(r"\s#", text, maxsplit=1)[0].rstrip()


def parse_profile(text):
    """The flat profile subset: `key: value`, and `key:` followed by `- item` lines."""
    values, list_key = {}, None
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "-" or stripped.startswith("- "):
            if list_key is not None:
                item = _scalar(stripped[1:])
                if item:
                    values[list_key].append(item)
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*):(?:[ ]+(.*))?$", raw.rstrip())
        if not match or raw[:1] == " ":
            list_key = None
            continue
        value = _scalar(match.group(2) or "")
        if value is None:
            values[match.group(1)] = []
            list_key = match.group(1)
        else:
            values[match.group(1)] = value
            list_key = None
    return values


def load_profile():
    """The repository profile with the machine's local profile over it, or None when absent."""
    base = harness_dir() / "profile.yaml"
    if not base.is_file():
        return None
    profile = parse_profile(base.read_text(encoding="utf-8"))
    local = base.with_name("profile.local.yaml")
    if local.is_file():
        profile.update(parse_profile(local.read_text(encoding="utf-8")))
    return profile


def setting(profile, key):
    """A scalar profile value, or "" when the key is missing, empty or `none`."""
    value = profile.get(key)
    if not isinstance(value, str) or value.strip().lower() in ("", "none"):
        return ""
    return value.strip()


def read_event():
    """The whole hook input from stdin as a dict, or None when stdin is not a JSON object. A
    PostToolUse hook needs more than the call: `tool_response` (or `error` after a failure),
    `tool_use_id` and `session_id`."""
    try:
        data = json.loads(sys.stdin.read())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def read_call():
    """(tool_name, tool_input) from stdin, or None when stdin is not a JSON tool call."""
    data = read_event()
    if data is None:
        return None
    tool_input = data.get("tool_input")
    return str(data.get("tool_name") or ""), tool_input if isinstance(tool_input, dict) else {}


OPERATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "!", ";;"}


def _lex(command):
    lexer = shlex.shlex(command.replace("\n", " ; ").replace("`", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def lex(command):
    """The words of a shell command with operators as their own tokens, quoted words kept whole. A
    command shlex cannot split (an unbalanced quote, an apostrophe in a heredoc body) is split at
    whitespace and operators instead."""
    try:
        return _lex(command)
    except ValueError:
        return re.findall(r"[;&|()]+|[^\s;&|()]+", command)


def tokens(command, depth=0):
    """The words of a shell command with operators as their own tokens. A quoted word that holds a
    command of its own (`bash -c "..."`) is opened up, so what it runs is seen too."""
    words = lex(command)
    out = []
    for word in words:
        if depth < 3 and re.search(r"\s", word):
            out += ["("] + tokens(word, depth + 1) + [")"]
        elif word != "$":
            out.append(word)
    return out


def segments(command):
    """The simple commands of a shell command line: lists of words split at the operators."""
    current, out = [], []
    for word in tokens(command):
        if word in OPERATORS or set(word) <= set(";&|()"):
            if current:
                out.append(current)
            current = []
        else:
            current.append(word)
    if current:
        out.append(current)
    return out


def command_words(segment):
    """The segment without its leading `VAR=value` assignments."""
    index = 0
    while index < len(segment) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[index]):
        index += 1
    return segment[index:]


def run(main):
    """Run a hook's main(call, profile) -> (code, message), failing open on any error."""
    try:
        call = read_call()
        if call is None:
            return ALLOW
        profile = load_profile()
        if profile is None:
            return ALLOW
        code, message = main(call[0], call[1], profile)
    except Exception:  # a broken hook must never stop a session
        return ALLOW
    if code == BLOCK and message:
        print(message, file=sys.stderr)
    return BLOCK if code == BLOCK else ALLOW


def entry(main):
    sys.exit(run(main))
