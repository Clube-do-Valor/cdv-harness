#!/usr/bin/env python3
"""Render the brief a child of a kickoff run starts from.

    brief.py render <role> [--root <repo>] [--run <run profile>]

The brief carries what a child on any account needs and cannot inherit: the run profile path, the
role, the skill to load, the vendored references, the gate commands of the repository profile and
the unattended rule. The orchestrator adds the task of the stage below it. Exit 0, 2 when there is
no valid run profile or the role is unknown.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_common import (  # noqa: E402
    BAD_INPUT,
    OK,
    ROLES,
    ScriptError,
    find_run_profile,
    load_run_profile,
    repo_profile,
    run_folder,
    setting,
)

# Role -> (skill to load, what to do with it).
ROLE_SKILL = {
    "orchestrator": ("cdv-kickoff", "run the chain of the run profile"),
    "builder": ("tlc-spec-lean", "Build phase: one slice at a time, S1 first, one commit per slice; when the review is back, the one fix pass"),
    "builder_risk": ("tlc-spec-lean", "Build phase: one slice at a time, S1 first, one commit per slice; when the review is back, the one fix pass"),
    "verifier": ("tlc-spec-lean", "Review phase: the prompt of references/review.md, filled; you are not the author, change no code and commit nothing, write review.md"),
    "reviewer": ("cdv-code-review", "bugs and regressions only: no refactor, no style"),
    "fixer": ("cdv-apply-review", "one commit per finding, on the same branch"),
    "qa": ("cdv-qa", "drive the browser yourself and record every step"),
    "research": ("cdv-research-round", "one research round into the feature's work folder"),
    "judge": ("cdv-kickoff", "the blind-judges recipe: .claude/skills/cdv-kickoff/references/optional/blind-judges.md"),
}

# Gate commands of the repository profile, in the order they run.
GATE_KEYS = [
    "cmd_format_backend",
    "cmd_test_backend",
    "cmd_test_backend_filter",
    "cmd_static_analysis",
    "cmd_format_frontend",
    "cmd_lint_frontend",
    "cmd_test_frontend",
    "cmd_build_frontend",
]

UNATTENDED_RULE = (
    "Unattended rule (`unattended: own-test-records`): the developer is away. Commits, pushes, the pull "
    "request, the card, browser QA and production reads go on without asking; the only external records "
    "you may create are this run's own test records, each named with `profile.qa_test_marker`, registered "
    "before it is created and deleted at the end. Stop and ask before any step that sends something to a "
    "person or a live automation, writes in production or deploys."
)


def render_brief(root, profile_path, run, repo, role):
    if role not in ROLE_SKILL:
        raise ScriptError(f"unknown role `{role}`: one of {', '.join(ROLES)}")
    root = Path(root)
    skill, task = ROLE_SKILL[role]
    relative = profile_path.relative_to(root) if profile_path.is_relative_to(root) else profile_path
    folder = run_folder(root, profile_path)
    folder = folder.relative_to(root) if folder.is_relative_to(root) else folder
    lines = [
        f"# Brief - role `{role}` of `{run['feature']}`",
        "",
        f"Run profile: `{relative}` - read it first: it is the contract of this run "
        f"(track {run['track']}, mode {run['mode']}, workspace {run['workspace']}).",
        f"Work folder: `{folder}/` - status, QA report, manifest and screenshots go here; never commit it.",
        f"Role: `{role}`.",
        f"Skill to load: `{skill}` (`.claude/skills/{skill}/SKILL.md`) - {task}.",
    ]
    if role in ("builder", "builder_risk"):
        fault = run.get("fault_injection") == "true"
        lines.append(
            "Fault injection: "
            + ("on - break each guard once, see its test fail, restore it." if fault else "off.")
        )
    references = sorted((root / ".claude" / "harness" / "references").glob("*.md"))
    lines += ["", "References (read the ones your step needs):"]
    lines += [f"- `{p.relative_to(root)}`" for p in references] or ["- none vendored in this checkout"]
    gates = [(key, setting(repo, key)) for key in GATE_KEYS if setting(repo, key)]
    lines += ["", "Gates of the repository profile (green before every commit; one heavy command at a time):"]
    lines += [f"- {key}: `{value}`" for key, value in gates] or ["- none declared"]
    lines += [
        "",
        UNATTENDED_RULE,
        "",
        "Models: every child you start names its model from the role table (`role_target.py <role>`); "
        "never inherit, and Fable only when the user names it.",
        "Stops of this run: " + (", ".join(run.get("stops") or []) or "none") + ".",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: the current directory)")
    parser.add_argument("--run", help="the run profile file (default: the only one under the root)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("render").add_argument("role")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        profile_path = find_run_profile(root, args.run).resolve()
        profile = load_run_profile(profile_path)
        sys.stdout.write(render_brief(root, profile_path, profile, repo_profile(root), args.role))
    except ScriptError as error:
        print(f"brief: {error}", file=sys.stderr)
        return BAD_INPUT
    return OK


if __name__ == "__main__":
    sys.exit(main())
