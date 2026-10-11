"""The tools the model can call, confined to one project checkout.

Which tools may write where depends on the phase:
  read       - nothing is written
  reproduce  - only test files may be written
  fix        - only non-test files may be written
The tool list itself never changes between phases (that keeps the prompt cache
warm); the workspace refuses calls the current phase does not allow.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from . import tracing
from .pytest_run import clip, run_pytest

READ, REPRODUCE, FIX = "read", "reproduce", "fix"

_SKIP_DIRS = {".git", ".venv", "venv", ".tox", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", "build", "dist"}


def is_test_path(rel: str) -> bool:
    parts = Path(rel.replace("\\", "/")).parts
    if not parts:
        return False
    name = parts[-1]
    return (
        any(p in ("tests", "testing", "test") for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


class ToolError(Exception):
    pass


# Never hand these to the project under test: its code and the model's commands run there.
SECRET_VARS = ("ANTHROPIC_API_KEY", "WINCHECK_ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "NEATLOGS_API_KEY",
               "GITHUB_TOKEN", "GH_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")


def scrub(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k.upper() not in SECRET_VARS}


class Workspace:
    def __init__(self, root: Path, python: str, env: dict[str, str] | None = None):
        self.root = root.resolve()
        self.python = python
        self.env = scrub(env or os.environ.copy())
        self.phase = READ
        # Set by the agent when a phase-changing tool is called.
        self.submission: tuple[str, dict[str, Any]] | None = None

    # -- helpers ---------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if path != self.root and self.root not in path.parents:
            raise ToolError(f"{rel!r} is outside the project")
        return path

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def check_write(self, rel: str) -> None:
        if self.phase == READ:
            raise ToolError("Nothing can be written while reading the issue. Call start_reproduction first.")
        test = is_test_path(rel)
        if self.phase == REPRODUCE and not test:
            raise ToolError(
                f"{rel} is not a test file. During reproduction only test files may change; "
                "the source stays untouched until a failing test exists."
            )
        if self.phase == FIX and test:
            raise ToolError(f"{rel} is a test file. Test files are frozen once the reproduction is accepted.")

    # -- tools -----------------------------------------------------------
    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"{path} is not a file")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        end = min(end_line or len(lines), len(lines))
        start = max(start_line, 1)
        body = "\n".join(f"{i:>5}  {lines[i - 1]}" for i in range(start, end + 1))
        return clip(f"{path} (lines {start}-{end} of {len(lines)})\n{body}", 40000)

    def list_dir(self, path: str = ".") -> str:
        p = self.resolve(path)
        if not p.is_dir():
            raise ToolError(f"{path} is not a directory")
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        out = [e.name + ("/" if e.is_dir() else "") for e in entries if e.name not in _SKIP_DIRS]
        return "\n".join(out) or "(empty)"

    def search(self, pattern: str, path: str = ".", glob: str = "*.py") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"bad regex: {exc}") from exc
        base = self.resolve(path)
        hits: list[str] = []
        files = [base] if base.is_file() else base.rglob(glob)
        for f in files:
            if any(part in _SKIP_DIRS for part in f.relative_to(self.root).parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self.rel(f)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n(stopped at 200 matches)"
        return "\n".join(hits) or "no matches"

    def write_file(self, path: str, content: str) -> str:
        self.check_write(path)
        p = self.resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the line endings exactly as the model wrote them
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        return f"wrote {path} ({len(content)} chars)"

    def edit_file(self, path: str, old: str, new: str) -> str:
        self.check_write(path)
        p = self.resolve(path)
        if not p.is_file():
            raise ToolError(f"{path} does not exist")
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n") if crlf else raw
        count = text.count(old)
        if count != 1:
            raise ToolError(f"`old` must match exactly once in {path}; it matched {count} times")
        text = text.replace(old, new, 1)
        if crlf:
            text = text.replace("\n", "\r\n")
        p.write_bytes(text.encode("utf-8"))
        return f"edited {path}"

    def run_command(self, command: str, timeout: int = 300) -> str:
        if self.phase == READ:
            raise ToolError("Commands can be run from the reproduction phase on. Call start_reproduction first.")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(timeout, 900),
                env=self.env,
            )
        except subprocess.TimeoutExpired:
            return f"timed out after {timeout}s"
        return clip(f"exit code {proc.returncode}\n{proc.stdout}\n{proc.stderr}")

    def run_tests(self, test_ids: list[str]) -> str:
        if self.phase == READ:
            raise ToolError("Tests can be run from the reproduction phase on. Call start_reproduction first.")
        res = run_pytest(self.python, self.root, test_ids, env=self.env)
        summary = "\n".join(f"{v:7} {k}" for k, v in res.outcomes.items()) or "(no per-test results)"
        return clip(f"exit code {res.returncode}\n{summary}\n\n--- output ---\n{res.output}")

    # Phase changes. These only record the request; the agent loop checks it.
    def start_reproduction(self, plan: str) -> str:
        if self.phase != READ:
            raise ToolError("Already past the read phase.")
        self.submission = ("start_reproduction", {"plan": plan})
        return "ok"

    def submit_reproduction(self, test_ids: list[str], explanation: str) -> str:
        if self.phase != REPRODUCE:
            raise ToolError("submit_reproduction is only valid during reproduction.")
        bad = [t for t in test_ids if not is_test_path(t.split("::", 1)[0])]
        if not test_ids or bad:
            raise ToolError(f"Give pytest node ids inside test files. Rejected: {bad or 'empty list'}")
        self.submission = ("submit_reproduction", {"test_ids": test_ids, "explanation": explanation})
        return "submitted; the harness will run these tests now"

    def submit_fix(self, summary: str) -> str:
        if self.phase != FIX:
            raise ToolError("submit_fix is only valid during the fix phase.")
        self.submission = ("submit_fix", {"summary": summary})
        return "submitted; the harness will verify now"

    def give_up(self, reason: str) -> str:
        self.submission = ("give_up", {"reason": reason})
        return "ok"


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_S = {"type": "string"}
_I = {"type": "integer"}
_IDS = {"type": "array", "items": {"type": "string"}}

TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "read_file", "description": "Read a text file from the project, with line numbers. Optionally a line range.",
     "input_schema": _schema({"path": _S, "start_line": _I, "end_line": _I}, ["path"])},
    {"name": "list_dir", "description": "List a directory in the project.",
     "input_schema": _schema({"path": _S}, [])},
    {"name": "search", "description": "Regex search over project files (default *.py). Returns path:line: text.",
     "input_schema": _schema({"pattern": _S, "path": _S, "glob": _S}, ["pattern"])},
    {"name": "write_file", "description": "Create or overwrite a file. Content is written byte for byte (no newline translation).",
     "input_schema": _schema({"path": _S, "content": _S}, ["path", "content"])},
    {"name": "edit_file", "description": "Replace one exact occurrence of `old` with `new` in a file. Line endings of the file are preserved.",
     "input_schema": _schema({"path": _S, "old": _S, "new": _S}, ["path", "old", "new"])},
    {"name": "run_command", "description": "Run a shell command in the project root, inside the project's virtualenv. Returns exit code and output.",
     "input_schema": _schema({"command": _S, "timeout": _I}, ["command"])},
    {"name": "run_tests", "description": "Run pytest node ids (e.g. tests/test_x.py::test_y) and get per-test outcomes plus output.",
     "input_schema": _schema({"test_ids": _IDS}, ["test_ids"])},
    {"name": "start_reproduction", "description": "Leave the read phase. Say what the bug is and how you will reproduce it.",
     "input_schema": _schema({"plan": _S}, ["plan"])},
    {"name": "submit_reproduction", "description": "Submit the pytest node ids that reproduce the bug. The harness runs them; every one must FAIL on this machine for the reproduction to be accepted.",
     "input_schema": _schema({"test_ids": _IDS, "explanation": _S}, ["test_ids", "explanation"])},
    {"name": "submit_fix", "description": "Submit the fix. The harness re-runs the reproduction tests (must pass) and the test files they live in (no new failures).",
     "input_schema": _schema({"summary": _S}, ["summary"])},
    {"name": "give_up", "description": "Stop without a patch, e.g. when the bug cannot be reproduced on this machine. Explain why.",
     "input_schema": _schema({"reason": _S}, ["reason"])},
]

for _spec in TOOL_SPECS:
    _spec["eager_input_streaming"] = True


def validate_input(spec: dict[str, Any], data: Any) -> str | None:
    """Check a (possibly truncated) streamed tool input against its schema."""
    if not isinstance(data, dict):
        return "input is not a JSON object"
    schema = spec["input_schema"]
    for key in schema["required"]:
        if key not in data:
            return f"missing required field {key!r}"
    for key, value in data.items():
        prop = schema["properties"].get(key)
        if prop is None:
            return f"unknown field {key!r}"
        kind = prop["type"]
        ok = (
            (kind == "string" and isinstance(value, str))
            or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (kind == "array" and isinstance(value, list) and all(isinstance(v, str) for v in value))
        )
        if not ok:
            return f"field {key!r} should be {kind}"
    return None


def build_dispatch(ws: Workspace) -> dict[str, Callable[..., str]]:
    """Map tool names to workspace methods, each wrapped in a neatlogs TOOL span."""
    return {
        spec["name"]: tracing.span(kind="TOOL", name=spec["name"], tool_name=spec["name"])(getattr(ws, spec["name"]))
        for spec in TOOL_SPECS
    }


def venv_python(venv: Path) -> str:
    sub = "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    return str(venv / sub)
