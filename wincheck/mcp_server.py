"""MCP server that exposes Wincheck to Claude and other MCP clients.

  pip install -e ".[mcp]"
  wincheck-mcp            # stdio transport

Every tool runs `python -m wincheck ...` in a subprocess, so the agent's own
output never reaches the MCP stdout stream. Runs are written under
WINCHECK_HOME (default ~/wincheck).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

TIMEOUT = 60 * 60  # a full agent run plus scoring can take a while
STDERR_TAIL = 40

mcp = FastMCP("wincheck")


def _home() -> Path:
    home = Path(os.environ.get("WINCHECK_HOME") or Path.home() / "wincheck")
    home.mkdir(parents=True, exist_ok=True)
    return home


def _last_json(stdout: str) -> Any:
    """The CLI prints log lines and then one indented JSON object; return that object."""
    if stdout.startswith("{\n"):
        start = 0
    else:
        start = stdout.rfind("\n{\n") + 1
        if start == 0:
            return None
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return None


def _wincheck(*args: str) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "wincheck", *args]
    try:
        p = subprocess.run(cmd, cwd=_home(), stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"exit_code": None, "error": f"timed out after {TIMEOUT // 60} minutes"}
    out: dict[str, Any] = {"exit_code": p.returncode, "result": _last_json(p.stdout)}
    if p.returncode != 0:
        out["stderr_tail"] = "\n".join(p.stderr.splitlines()[-STDERR_TAIL:])
    return out


@mcp.tool()
def list_cases() -> dict[str, Any]:
    """List the eval cases: name, split (dev or held_out) and upstream repo@commit."""
    p = subprocess.run([sys.executable, "-m", "wincheck", "cases"], cwd=_home(), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    cases = []
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            cases.append({"name": parts[0], "split": parts[1], "upstream": parts[2]})
    out: dict[str, Any] = {"exit_code": p.returncode, "result": cases}
    if p.returncode != 0:
        out["stderr_tail"] = "\n".join(p.stderr.splitlines()[-STDERR_TAIL:])
    return out


@mcp.tool()
def check_case(case: str) -> dict[str, Any]:
    """Check that a case's bug reproduces on this machine (baseline only, no model calls)."""
    return _wincheck("eval", case, "--baseline-only")


@mcp.tool()
def run_case(case: str, effort: str = "high", held_out: bool = False) -> dict[str, Any]:
    """Run the agent on a case and score it with the maintainers' tests. Needs ANTHROPIC_API_KEY.

    Set held_out to true to score a held-out case.
    """
    args = ["eval", case, "--effort", effort]
    if held_out:
        args.append("--held-out")
    return _wincheck(*args)


@mcp.tool()
def fix_issue(repo_path: str, issue_text: str, python_path: str | None = None) -> dict[str, Any]:
    """Run the agent on a local checkout with the given bug report. Needs ANTHROPIC_API_KEY.

    python_path is the python of the project's environment (defaults to the server's python).
    """
    with tempfile.TemporaryDirectory() as tmp:
        issue = Path(tmp) / "issue.md"
        issue.write_text(issue_text, encoding="utf-8")
        args = ["run", "--repo", str(Path(repo_path).resolve()), "--issue-file", str(issue)]
        if python_path:
            args += ["--python", python_path]
        return _wincheck(*args)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
