#!/usr/bin/env python3
"""Resolve a role of the run to the target a child is started with.

    role_target.py <role> [--named-by-user] [--root <repo>] [--run <run profile>]

Reads the role line `role_<role>: <account> <model alias> <effort>` of the repository profile
(`.claude/harness/profile.yaml`, with `profile.local.yaml` over it) - or of the run profile given
with --run, whose role line wins for that run - and maps the account through `account_<name>` and
the alias through `model_<alias>`. Prints one JSON object: role, provider, model, effort,
delegate_tool. Exits 2 naming the missing key when the role, its role line, its `account_<name>`
or its `model_<alias>` is not declared; on the alias `inherit`; and on the alias `fable` unless
the user named that model for this run (`--named-by-user`).
"""

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_common import BAD_INPUT, EFFORTS, OK, ROLES, ScriptError, parse_flat, repo_profile, setting  # noqa: E402


def resolve(role, profile, run_values=None, named_by_user=False):
    if role not in ROLES:
        raise ScriptError(f"unknown role `{role}`: one of {', '.join(ROLES)}")
    key = f"role_{role}"
    line = setting(run_values or {}, key) or setting(profile, key)
    if not line:
        raise ScriptError(f"`{key}` is not declared in the repository profile")
    words = line.split()
    if len(words) != 3 or words[2] not in EFFORTS:
        raise ScriptError(f"`{key}: {line}` must be `<account> <model alias> <effort>` with effort in {', '.join(EFFORTS)}")
    account, alias, effort = words
    if alias == "inherit":
        raise ScriptError(f"`{key}` names the alias `inherit`: every child names its model")
    if alias == "fable" and not named_by_user:
        raise ScriptError(f"`{key}` resolves to `fable`, which runs only when the user names it for this run (--named-by-user)")
    provider = setting(profile, f"account_{account}")
    if not provider:
        raise ScriptError(f"`account_{account}` is not declared (profile.local.yaml maps the account to the host's provider id)")
    model = setting(profile, f"model_{alias}")
    if not model:
        raise ScriptError(f"`model_{alias}` is not declared (profile.local.yaml maps the alias to the host's model id)")
    return {
        "role": role,
        "provider": provider,
        "model": model,
        "effort": effort,
        "delegate_tool": setting(profile, "delegate_tool") or "none",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("role")
    parser.add_argument("--named-by-user", action="store_true", help="the user named this model for this run")
    parser.add_argument("--root", default=".", help="repository root (default: the current directory)")
    parser.add_argument("--run", help="a run profile whose role line wins for this run")
    args = parser.parse_args(argv)
    try:
        run_values = {}
        if args.run:
            run_path = Path(args.run) if Path(args.run).is_absolute() else Path(args.root) / args.run
            if not run_path.is_file():
                raise ScriptError(f"no run profile at {args.run}")
            run_values = parse_flat(run_path.read_text(encoding="utf-8"))
        target = resolve(args.role, repo_profile(args.root), run_values, args.named_by_user)
    except ScriptError as error:
        print(f"role_target: {error}", file=sys.stderr)
        return BAD_INPUT
    print(json.dumps(target))
    return OK


if __name__ == "__main__":
    sys.exit(main())
