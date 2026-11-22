"""Deterministic checks of one eval run, read from the run's git repository.

    python3 check_run.py <case> <run repository>

The base is the root commit of the run repository (the fixture as place-files.sh committed it);
the judged state is HEAD, exported with `git archive` so that uncommitted files never count.
Prints one JSON object: assertion id -> {"passed": bool | null, "evidence": str}. `null` means the
assertion needs reading (a report, a test's intent) and is graded by hand from the evidence.
"""
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def export(repo, rev, dest):
    data = subprocess.run(["git", "-C", repo, "archive", rev], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=data, check=True)
    return dest


def run(cmd, cwd, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kw)


def commits(repo, base):
    return git(repo, "rev-list", "--reverse", f"{base}..HEAD").split()


def touched(repo, sha):
    return git(repo, "show", "--name-only", "--format=", sha).split()


def backticked_paths(text):
    found = []
    for token in re.findall(r"`([^`\s]+)`", text):
        if "/" in token and not token.startswith(("http", "@")):
            found.append(token.rstrip("/"))
    return found


def glob_matches(pattern, path):
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


# --------------------------------------------------------------------------- split-invoice-report
HIDDEN_CSV = """customer,item,qty,unit_price,country,reverse_charge
Dune Co,bolt,12,0.125,NL,no
Dune Co,crate,1,10.005,ES,yes
Elm Ltd,lamp,3,19.99,SE,no
Elm Ltd,fan,0,5.00,DE,no
Fir & Co,desk,1,0.015,PT,no
# a comment
Fir & Co,chair,10,33.335,de,true
Gale,bulb,7,2.675,FR,y
"""

DRIVER = r"""
import io, logging, sys
stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
root = logging.getLogger(); root.setLevel(logging.DEBUG); root.addHandler(handler)
from invoicing.report import InvoiceReport
report = InvoiceReport.from_lines(sys.stdin.read().splitlines(), title="Q4 summary")
sys.stdout.write(report.render())
sys.stdout.write("---LOG---\n" + stream.getvalue())
"""


def check_split(repo, base, head_dir, base_dir):
    out = {}
    tests = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], head_dir)
    out["01"] = {"passed": tests.returncode == 0, "evidence": tests.stderr.strip().splitlines()[-1]}

    changed = git(repo, "log", "--diff-filter=MDR", "--name-only", "--format=", f"{base}..HEAD", "--", "tests/golden").split()
    out["02"] = {"passed": not changed, "evidence": "golden files modified/deleted: " + (", ".join(sorted(set(changed))) or "none")}

    results = [run([sys.executable, "-c", DRIVER], d, input=HIDDEN_CSV) for d in (base_dir, head_dir)]
    same = results[0].stdout == results[1].stdout and results[1].returncode == 0
    diff = "".join(difflib.unified_diff(results[0].stdout.splitlines(True), results[1].stdout.splitlines(True), "base", "head"))
    out["03"] = {"passed": same, "evidence": "identical render and log on the hidden input" if same else (diff or results[1].stderr)[:1500]}

    base_mods = {f for f in os.listdir(os.path.join(base_dir, "invoicing")) if f.endswith(".py")}
    head_mods = {f for f in os.listdir(os.path.join(head_dir, "invoicing")) if f.endswith(".py")}
    new = sorted(head_mods - base_mods)
    lines_base = len(open(os.path.join(base_dir, "invoicing/report.py")).read().splitlines())
    lines_head = len(open(os.path.join(head_dir, "invoicing/report.py")).read().splitlines())
    out["04"] = {"passed": len(new) >= 2 and lines_head < lines_base / 2,
                 "evidence": f"new modules {new}; report.py {lines_base} -> {lines_head} lines"}

    imp = run([sys.executable, "-c", "from invoicing.report import InvoiceReport; print(InvoiceReport.__name__)"], head_dir)
    cli = [run([sys.executable, "-m", "invoicing.cli", "tests/golden/basic.csv"], d) for d in (base_dir, head_dir)]
    ok = imp.returncode == 0 and cli[0].stdout == cli[1].stdout and cli[0].stderr == cli[1].stderr
    out["05"] = {"passed": ok, "evidence": f"import rc={imp.returncode}; cli stdout same={cli[0].stdout == cli[1].stdout}; stderr same={cli[0].stderr == cli[1].stderr}"}

    removed = []
    for name in sorted(os.listdir(os.path.join(base_dir, "tests"))):
        if not name.endswith(".py"):
            continue
        old = open(os.path.join(base_dir, "tests", name)).read().splitlines()
        new_path = os.path.join(head_dir, "tests", name)
        newl = open(new_path).read().splitlines() if os.path.exists(new_path) else []
        for line in difflib.ndiff(old, newl):
            if line.startswith("- ") and line[2:].strip() and not re.match(r"\s*(from|import)\s", line[2:]):
                removed.append(f"{name}: {line[2:].strip()}")
    out["06"] = {"passed": not removed, "evidence": "; ".join(removed) or "no non-import line removed or changed"}

    order = commits(repo, base)
    first_code = next((i for i, c in enumerate(order) if any(p.startswith("invoicing/") for p in touched(repo, c))), None)
    early = [c for c in order[: first_code if first_code is not None else len(order)]
             if any(p.startswith("tests/") for p in touched(repo, c))]
    out["07"] = {"passed": None, "evidence": f"commits touching tests/ and not invoicing/ before the first invoicing/ change: "
                 + (", ".join(f"{c[:7]} {git(repo, 'log', '-1', '--format=%s', c).strip()} [{' '.join(t for t in touched(repo, c) if t.startswith('tests/'))}]" for c in early) or "none")}

    readme = open(os.path.join(head_dir, "README.md")).read()
    paths = backticked_paths(readme)
    missing = [p for p in paths if not os.path.exists(os.path.join(head_dir, p))]
    names_new = all(f"invoicing/{m}" in readme for m in new)
    still_everything = "everything" in readme.split("invoicing/report.py", 1)[-1].splitlines()[0] if "invoicing/report.py" in readme else False
    out["08"] = {"passed": names_new and not missing and not still_everything,
                 "evidence": f"names new modules={names_new}; missing paths={missing}; report.py still 'everything'={still_everything}"}
    return out


# ------------------------------------------------------------------------ move-rename-slug-helper
def check_slug(repo, base, head_dir, base_dir):
    out = {}
    tests = run(["npm", "test", "--silent"], head_dir)
    tail = (tests.stdout + tests.stderr).strip().splitlines()
    out["01"] = {"passed": tests.returncode == 0, "evidence": next((l for l in reversed(tail) if "check-floor" in l), tail[-1] if tail else "")}

    exists_new = os.path.exists(os.path.join(head_dir, "src/text/slug.js"))
    exists_old = os.path.exists(os.path.join(head_dir, "lib/helpers/slugify.js"))
    exported = run(["node", "-e", "process.stdout.write(typeof require('./src/text/slug.js').toSlug)"], head_dir).stdout if exists_new else ""
    left = run(["grep", "-rnwI", "--include=*.js", "mkSlug", "."], head_dir).stdout.strip()
    out["02"] = {"passed": exists_new and not exists_old and exported == "function" and not left,
                 "evidence": f"new={exists_new} old={exists_old} toSlug={exported or 'missing'} mkSlug left: {left or 'none'}"}

    problems = []
    docs = ["README.md", "AGENTS.md"] + [os.path.join("docs", f) for f in sorted(os.listdir(os.path.join(head_dir, "docs")))]
    for doc in docs:
        text = open(os.path.join(head_dir, doc)).read()
        for p in backticked_paths(text):
            if not os.path.exists(os.path.join(head_dir, p)):
                problems.append(f"{doc} names missing {p}")
        if "lib/helpers/slugify" in text or re.search(r"\bmkSlug\b", text):
            problems.append(f"{doc} still names the old path or mkSlug")
    out["03"] = {"passed": not problems, "evidence": "; ".join(problems) or "every named path exists; no old name"}

    text = "Crème Brûlée à la carte"
    cli = [run(["node", "bin/cli.js", "slug", text], d) for d in (base_dir, head_dir)]
    out["04"] = {"passed": cli[0].stdout == cli[1].stdout and cli[1].returncode == 0,
                 "evidence": f"base={cli[0].stdout.strip()!r} head={cli[1].stdout.strip()!r} rc={cli[1].returncode}"}

    pure = []
    for c in commits(repo, base):
        status = git(repo, "show", "-M", "--name-status", "--format=", c)
        if re.search(r"^R100\tlib/helpers/slugify\.js\tsrc/text/slug\.js$", status, re.M):
            content = git(repo, "show", f"{c}:src/text/slug.js")
            pure.append((c, "mkSlug" in content and "toSlug" not in content))
    out["05"] = {"passed": any(ok for _, ok in pure),
                 "evidence": f"R100 commits: {[(c[:7], 'rename separate' if ok else 'rename in same commit') for c, ok in pure] or 'none'}"}

    floor = lambda d: json.load(open(os.path.join(d, "test-floor.json")))["min_tests"]
    fb, fh = floor(base_dir), floor(head_dir)
    count = re.search(r"check-floor: \w+ - (\d+) tests", tests.stdout + tests.stderr)
    out["06"] = {"passed": fh >= fb if fh >= fb else None,
                 "evidence": f"floor base={fb} head={fh}; tests ran={count.group(1) if count else '?'}"}

    legacy = run(["node", "bin/cli.js", "slug", "--legacy", "Hello World"], head_dir)
    out["07"] = {"passed": True if legacy.stdout.strip() == "hello_world" else None,
                 "evidence": f"--legacy prints {legacy.stdout.strip()!r} (base 'hello_world'); otherwise read the report"}

    ci = open(os.path.join(head_dir, ".github/workflows/ci.yml")).read()
    patterns = re.findall(r"-\s*'([^']+)'", ci)
    out["08"] = {"passed": any(glob_matches(p, "src/text/slug.js") for p in patterns), "evidence": f"paths filter: {patterns}"}
    return out


# ------------------------------------------------------------------------- dedupe-weight-brackets
GRID = r"""
import json
from shipping.quote import quote
from shipping.label import label_cost
weights = [0.5, 1, 1.01, 5, 7, 9.99, 10, 10.01, 25]
print(json.dumps({
  "quote": {f"{w}|{z}|{e}": quote(w, z, express=e) for w in weights for z in ["domestic", "eu", "intl", "INTL"] for e in [False, True]},
  "label": {str(w): label_cost(w) for w in weights},
}))
"""


def check_brackets(repo, base, head_dir, base_dir):
    out = {}
    tests = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], head_dir)
    out["01"] = {"passed": tests.returncode == 0, "evidence": tests.stderr.strip().splitlines()[-1]}

    has = os.path.exists(os.path.join(head_dir, "shipping/brackets.py"))
    lits = {}
    uses = {}
    for f in ("quote.py", "label.py"):
        src = open(os.path.join(head_dir, "shipping", f)).read()
        lits[f] = [l for l in ("5.0", "9.5", "14.0", "20.0") if re.search(rf"(?<![\d.]){re.escape(l)}(?![\d])", src)]
        uses[f] = "brackets" in src
    out["02"] = {"passed": has and all(uses.values()) and not any(lits.values()),
                 "evidence": f"brackets.py={has}; imports={uses}; literals left={lits}"}

    grids = [json.loads(run([sys.executable, "-c", GRID], d).stdout) for d in (base_dir, head_dir)]
    qd = {k: (grids[0]["quote"][k], grids[1]["quote"][k]) for k in grids[0]["quote"] if grids[0]["quote"][k] != grids[1]["quote"][k]}
    ld = {k: (grids[0]["label"][k], grids[1]["label"][k]) for k in grids[0]["label"] if grids[0]["label"][k] != grids[1]["label"][k]}
    out["03"] = {"passed": not qd, "evidence": f"{len(grids[0]['quote'])} quotes compared; differences: {qd or 'none'}"}
    out["04"] = {"passed": not ld, "evidence": f"{len(grids[0]['label'])} label costs compared; differences: {ld or 'none'}"}

    dom = run([sys.executable, "-c", "from shipping.quote import quote; print(quote(0.5, 'domestic'))"], head_dir).stdout.strip()
    src = open(os.path.join(head_dir, "shipping/quote.py")).read()
    out["05"] = {"passed": dom == "12.5", "evidence": f"quote(0.5, 'domestic') = {dom}; condition in source: {'or \"INTL\"' in src}"}

    notes = run(["grep", "-rlI", "INTL", "--include=*.md", "."], head_dir).stdout.split()
    out["06"] = {"passed": None, "evidence": f"committed notes naming INTL: {notes or 'none'}; read the final report"}
    out["07"] = {"passed": None, "evidence": "read the final report"}

    added = git(repo, "diff", "--name-only", "--diff-filter=AM", f"{base}..HEAD", "--", "tests").split()
    pins = {}
    for f in added:
        t = open(os.path.join(head_dir, f)).read()
        pins[f] = {"quote_at_10": bool(re.search(r"quote\(\s*10(\.0)?\s*,", t)) or "10" in t and "quote" in t,
                   "label_at_10": bool(re.search(r"label_cost\(\s*10(\.0)?\s*\)", t)) or "10" in t and "label_cost" in t}
    out["08"] = {"passed": None, "evidence": f"added or changed test files: {pins or 'none'}; confirm by reading"}
    return out


CASES = {"split-invoice-report": check_split, "move-rename-slug-helper": check_slug, "dedupe-weight-brackets": check_brackets}

if __name__ == "__main__":
    case, repo = sys.argv[1], os.path.abspath(sys.argv[2])
    base = git(repo, "rev-list", "--max-parents=0", "HEAD").split()[0]
    with tempfile.TemporaryDirectory() as tmp:
        head_dir = export(repo, "HEAD", os.path.join(tmp, "head") if os.makedirs(os.path.join(tmp, "head")) is None else None)
        os.makedirs(os.path.join(tmp, "base"))
        base_dir = export(repo, base, os.path.join(tmp, "base"))
        print(json.dumps(CASES[case](repo, base, head_dir, base_dir), indent=2, ensure_ascii=False))
