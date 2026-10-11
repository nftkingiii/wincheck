"""Eval cases: real Windows bugs fixed upstream, replayed from the commit before the fix.

The agent only sees the issue text and the checkout at <fix>^. Scoring uses the
maintainers' own test from the fix commit: the target tests must fail before
the agent runs and pass after, and no other test in those files that passed
before may fail.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import tracing
from .pytest_run import normalize_id, run_pytest
from .tools import is_test_path, scrub, venv_python


@dataclass(frozen=True)
class Case:
    name: str
    repo: str
    fix: str
    install: tuple[str, ...]
    split: str  # dev | held_out
    issue: int | None = None
    test_files: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()  # explicit target node ids; otherwise every test that fails before the fix
    expected: int | None = None  # sanity check on the number of derived targets
    exclude: tuple[str, ...] = ()  # substrings of node ids to ignore (environment noise)


CASES = {c.name: c for c in [
    Case("click-3277", "pallets/click", "e0d1678ebc10cc663f2bc1973e0399b31415f8db", ("-e", ".", "pytest"), "dev",
         issue=3277, test_files=("tests/test_shell_completion.py",),
         tests=("tests/test_shell_completion.py::test_source_uses_lf_line_endings",)),
    Case("tox-3222", "tox-dev/tox", "1bbc024ea3e4d81a33bed7753a91c7a357f8aae9", ("-e", ".", "--group", "test"), "dev",
         issue=3222, test_files=("tests/config/loader/test_str_convert.py",), expected=6,
         exclude=("test_setenv_path_not_overwritten",)),
    Case("click-tempfile-pager", "pallets/click", "fc5c7f45da0a4443f60ba2d322fe4bf829977739", ("-e", ".", "pytest"), "held_out",
         issue=3731, test_files=("tests/test_termui.py",), tests=("tests/test_termui.py::test_tempfile_pager_closes_file_before_unlink",)),
    Case("pytest-pathlib", "pytest-dev/pytest", "d6f66d42df86624ed128b84ce57df3d173fe1b95", ("-e", ".[dev]"), "held_out",
         issue=14864, test_files=("testing/test_pathlib.py",), expected=1),
    Case("tox-str-convert", "tox-dev/tox", "dc318dd64962f66b94e0abdccd81bf85be1c9c2e", ("-e", ".", "--group", "test"), "held_out",
         test_files=("tests/config/loader/test_str_convert.py",), expected=20, exclude=("test_setenv_path_not_overwritten",)),
    Case("build-env", "pypa/build", "854074059bfc3a872e44940d9dd49ee777cc0d33", ("-e", ".[virtualenv]", "--group", "test"), "held_out",
         test_files=("tests/test_env.py",), expected=1),
]}


def default_workdir() -> Path:
    if os.environ.get("WINCHECK_WORKDIR"):
        return Path(os.environ["WINCHECK_WORKDIR"])
    # Short paths on Windows: some of these test suites nest deep temp dirs (MAX_PATH).
    return Path("C:/wc") if sys.platform == "win32" else Path.cwd() / ".work"


def _short(case: Case) -> str:
    return re.sub(r"[^a-z0-9]", "", case.name)[:8]


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


# -- GitHub ------------------------------------------------------------------
def _gh(path: str) -> object:
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


_CLOSES = re.compile(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s+#(\d+)", re.I)


def resolve_issue(case: Case) -> int:
    """Issue number for the case: given, or found from the PR that landed the fix."""
    if case.issue:
        return case.issue
    texts = []
    for pr in _gh(f"repos/{case.repo}/commits/{case.fix}/pulls"):  # type: ignore[union-attr]
        texts.append(pr.get("body") or "")
    texts.append(_gh(f"repos/{case.repo}/commits/{case.fix}")["commit"]["message"])  # type: ignore[index]
    for text in texts:
        m = _CLOSES.search(text)
        if m:
            return int(m.group(1))
    raise RuntimeError(f"could not find the issue for {case.name}; set it in CASES")


# Reports written for cases whose upstream fix closes no issue (the PR text would give the fix away).
# They describe only the symptom, and score.json marks them as issue_source "written".
WRITTEN_ISSUES = Path(__file__).parent / "issues"


def written_issue(case: Case) -> Path | None:
    path = WRITTEN_ISSUES / f"{case.name}.md"
    return path if not case.issue and path.exists() else None


def issue_text(case: Case, number: int) -> str:
    issue = _gh(f"repos/{case.repo}/issues/{number}")
    return f"{case.repo}#{number}: {issue['title']}\n\n{issue.get('body') or ''}".strip()  # type: ignore[index]


# -- project setup -------------------------------------------------------------
@dataclass
class Project:
    case: Case
    src: Path
    python: str
    env: dict[str, str]
    test_files: list[str]


@tracing.span(kind="TOOL", name="prepare_project", capture_input=False, tool_name="prepare_project")
def prepare(case: Case, workdir: Path) -> Project:
    base = workdir / _short(case)
    src, venv = base / "src", base / "venv"
    if base.exists():
        shutil.rmtree(base, onerror=_force_remove)
    base.mkdir(parents=True)
    # Full clone, not blobless: on the Windows runner, git failed to fetch the fix
    # commit's test files on demand when they were overlaid.
    _run(["git", "clone", "--quiet", f"https://github.com/{case.repo}.git", str(src)], workdir)
    git(src, "checkout", "--quiet", f"{case.fix}^")
    # Agents commit nothing; this just makes `git diff` meaningful and quiet.
    git(src, "config", "user.email", "wincheck@localhost")
    git(src, "config", "user.name", "wincheck")
    _run([sys.executable, "-m", "venv", str(venv)], base)
    py = venv_python(venv)
    _run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip>=25.1"], src, scrub(os.environ.copy()))
    _run([py, "-m", "pip", "install", "--quiet", *case.install], src, scrub(os.environ.copy()))
    env = scrub(os.environ.copy())
    env.pop("PYTHONPATH", None)
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = str(Path(py).parent) + os.pathsep + env.get("PATH", "")
    files = list(case.test_files) or [
        f for f in git(src, "diff", "--name-only", f"{case.fix}^", case.fix).splitlines()
        if is_test_path(f) and f.endswith(".py")
    ]
    return Project(case, src, py, env, files)


def _force_remove(func, path, _exc):
    os.chmod(path, 0o700)
    func(path)


def _excluded(case: Case, test_id: str) -> bool:
    return any(x in test_id for x in case.exclude)


def _counted(p: Project, test_id: str) -> bool:
    """Only the case's own test files count. Suites that test pytest itself run
    an inner pytest whose summary lines (for tests in temp dirs) end up in the
    captured output."""
    path = normalize_id(test_id).partition("::")[0]
    return path in {f.replace("\\", "/") for f in p.test_files} and not _excluded(p.case, test_id)


def run_maintainer_tests(p: Project) -> dict[str, str]:
    """Overlay the maintainers' test files from the fix commit and run them."""
    git(p.src, "checkout", p.case.fix, "--", *p.test_files)
    res = run_pytest(p.python, p.src, p.test_files, env=p.env)
    return {k: v for k, v in res.outcomes.items() if _counted(p, k)}


def restore_test_files(p: Project) -> None:
    for f in p.test_files:
        tracked = subprocess.run(["git", "cat-file", "-e", f"HEAD:{f}"], cwd=p.src, capture_output=True).returncode == 0
        if tracked:
            git(p.src, "checkout", "HEAD", "--", f)
        else:
            git(p.src, "rm", "--quiet", "--cached", "--force", "--ignore-unmatch", f)
            (p.src / f).unlink(missing_ok=True)


@dataclass
class Baseline:
    targets: list[str]
    before: dict[str, str]
    after: dict[str, str] = field(default_factory=dict)
    valid: bool = False
    note: str = ""


@tracing.span(kind="TOOL", name="baseline", capture_input=False, tool_name="baseline")
def baseline(p: Project, check_fix: bool = False) -> Baseline:
    """Maintainers' tests at <fix>^ (targets must fail) and, optionally, at <fix> (targets must pass)."""
    before = run_maintainer_tests(p)
    restore_test_files(p)
    if p.case.tests:
        targets = list(p.case.tests)
    else:
        targets = sorted(t for t, o in before.items() if o in ("FAILED", "ERROR"))
    b = Baseline(targets, before)
    failing = [t for t in targets if before.get(t, "MISSING") in ("FAILED", "ERROR")]
    problems = []
    if len(failing) != len(targets):
        problems.append(f"targets not failing before the fix: {sorted(set(targets) - set(failing))}")
    if p.case.expected is not None and len(targets) != p.case.expected:
        problems.append(f"expected {p.case.expected} target tests, found {len(targets)}")
    if check_fix:
        git(p.src, "checkout", "--quiet", p.case.fix)
        res = run_pytest(p.python, p.src, p.test_files, env=p.env)
        b.after = {k: v for k, v in res.outcomes.items() if _counted(p, k)}
        git(p.src, "checkout", "--quiet", f"{p.case.fix}^")
        not_passing = [t for t in targets if b.after.get(t) != "PASSED"]
        if not_passing:
            problems.append(f"targets not passing at the fix: {not_passing}")
    b.valid = not problems
    b.note = "; ".join(problems)
    return b


@dataclass
class Score:
    case: str
    split: str
    issue: int
    passed: bool
    agent_status: str
    targets: dict[str, str]
    regressions: list[str]
    baseline_note: str
    run_dir: str
    agent: dict = field(default_factory=dict)
    issue_source: str = "github"


@tracing.span(kind="TOOL", name="score", capture_input=False, tool_name="score")
def score(p: Project, b: Baseline) -> tuple[dict[str, str], list[str]]:
    after = run_maintainer_tests(p)
    targets = {t: after.get(t, "MISSING") for t in b.targets}
    regressions = [t for t, o in b.before.items() if o == "PASSED" and after.get(t) not in ("PASSED", "XFAIL")]
    return targets, regressions


@tracing.span(kind="WORKFLOW", name="wincheck_eval", capture_input=False)
def evaluate(case: Case, runs_root: Path, workdir: Path, baseline_only: bool = False,
             issue_file: Path | None = None, **agent_kwargs) -> dict:
    from .agent import Agent
    from .tools import Workspace

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = (runs_root / case.name / stamp).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    source = "file" if issue_file else "github"
    if not issue_file and (issue_file := written_issue(case)):
        source = "written"
    if issue_file:
        number, text = case.issue or 0, issue_file.read_text(encoding="utf-8")
    else:
        number = resolve_issue(case)
        text = issue_text(case, number)
    (run_dir / "issue.md").write_text(text, encoding="utf-8")

    p = prepare(case, workdir)
    b = baseline(p, check_fix=baseline_only)
    (run_dir / "baseline.json").write_text(json.dumps(asdict(b), indent=2), encoding="utf-8")
    if baseline_only or not b.valid:
        out = {"case": case.name, "issue": number, "issue_source": source, "baseline_valid": b.valid, "note": b.note,
               "targets": b.targets, "run_dir": str(run_dir)}
        (run_dir / "score.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    ws = Workspace(p.src, p.python, p.env)
    result = Agent(ws, text, run_dir, **agent_kwargs).run()
    targets, regressions = score(p, b)
    passed = all(o == "PASSED" for o in targets.values()) and not regressions
    s = Score(case.name, case.split, number, passed, result.status, targets, regressions, b.note, str(run_dir),
              {k: v for k, v in asdict(result).items() if k != "diff"}, source)
    (run_dir / "score.json").write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    return asdict(s)
