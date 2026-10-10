"""Run pytest in the target project's environment and read back per-test outcomes."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# "PASSED tests/x.py::test_a" / "FAILED tests/x.py::test_b - AssertionError"
_SUMMARY = re.compile(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS|SKIPPED)\s+(.+?)\s*$")


@dataclass
class PytestResult:
    returncode: int
    outcomes: dict[str, str] = field(default_factory=dict)
    output: str = ""
    timed_out: bool = False

    def outcome(self, test_id: str) -> str:
        """Outcome for a node id, or "MISSING" when pytest never reported it."""
        if test_id in self.outcomes:
            return self.outcomes[test_id]
        norm = normalize_id(test_id)
        for tid, out in self.outcomes.items():
            if normalize_id(tid) == norm:
                return out
        return "MISSING"


def normalize_id(test_id: str) -> str:
    path, sep, rest = test_id.partition("::")
    return path.replace("\\", "/") + sep + rest


def parse_summary(output: str) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for line in output.splitlines():
        m = _SUMMARY.match(line)
        if not m:
            continue
        status, rest = m.groups()
        if status in ("FAILED", "ERROR") and " - " in rest:
            rest = rest.split(" - ", 1)[0]
        if status == "SKIPPED" or "::" not in rest:
            # skip lines look like "SKIPPED [1] path:line: reason"
            continue
        # an ERROR in teardown after a PASS should still count against the test
        if outcomes.get(rest) in ("FAILED", "ERROR"):
            continue
        outcomes[rest] = status
    return outcomes


def run_pytest(
    python: str,
    cwd: Path,
    args: list[str],
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> PytestResult:
    cmd = [python, "-m", "pytest", "-rA", "-p", "no:cacheprovider", "--color=no", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env or os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        return PytestResult(returncode=-1, output=_text(exc.stdout) + _text(exc.stderr), timed_out=True)
    output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    return PytestResult(proc.returncode, parse_summary(output), output)


def _text(data: str | bytes | None) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else data


def clip(text: str, limit: int = 20000) -> str:
    """Keep the head and the tail; pytest puts the useful part at the end."""
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    return f"{text[:head]}\n\n... [{len(text) - limit} chars cut] ...\n\n{text[-tail:]}"
