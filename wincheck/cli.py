"""Command line entry point.

  wincheck run --repo PATH --issue-file ISSUE.md [--python VENV_PYTHON]
  wincheck eval CASE [--baseline-only] [--held-out]
  wincheck cases
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import tracing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wincheck")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the agent on a local checkout")
    r.add_argument("--repo", type=Path, required=True)
    r.add_argument("--issue-file", type=Path, required=True)
    r.add_argument("--python", default=sys.executable, help="python of the project's environment")
    r.add_argument("--runs", type=Path, default=Path("runs"))
    r.add_argument("--effort", default="high")

    e = sub.add_parser("eval", help="replay an upstream Windows bug and score the agent")
    e.add_argument("case")
    e.add_argument("--baseline-only", action="store_true", help="only check the case is valid on this machine")
    e.add_argument("--held-out", action="store_true", help="allow scoring a held-out case")
    e.add_argument("--runs", type=Path, default=Path("runs"))
    e.add_argument("--workdir", type=Path)
    e.add_argument("--issue-file", type=Path, help="use this issue text instead of fetching it from GitHub")
    e.add_argument("--effort", default="high")

    sub.add_parser("cases", help="list eval cases")
    args = ap.parse_args(argv)

    if args.cmd == "cases":
        from .evals import CASES
        for c in CASES.values():
            print(f"{c.name:22} {c.split:9} {c.repo}@{c.fix[:10]}")
        return 0

    if args.cmd != "eval" or not args.baseline_only:
        from .agent import api_key
        if not api_key():
            print("Set ANTHROPIC_API_KEY (or WINCHECK_ANTHROPIC_API_KEY)", file=sys.stderr)
            return 2

    exporting = tracing.init(workflow_name="wincheck", tags=[args.cmd, getattr(args, "case", "local")])
    print(f"[wincheck] neatlogs export {'on' if exporting else 'off'}", flush=True)
    try:
        if args.cmd == "run":
            from .agent import Agent
            from .tools import Workspace
            env = os.environ.copy()
            env["PATH"] = str(Path(args.python).parent) + os.pathsep + env.get("PATH", "")
            ws = Workspace(args.repo, args.python, env)
            run_dir = args.runs / "local" / time.strftime("%Y%m%d-%H%M%S")
            result = Agent(ws, args.issue_file.read_text(encoding="utf-8"), run_dir, effort=args.effort).run()
            print(json.dumps({k: v for k, v in result.__dict__.items() if k != "diff"}, indent=2))
            return 0 if result.status == "fixed" else 1

        from .evals import CASES, default_workdir, evaluate
        case = CASES.get(args.case)
        if case is None:
            print(f"unknown case {args.case}; see `wincheck cases`", file=sys.stderr)
            return 2
        if case.split == "held_out" and not args.held_out and not args.baseline_only:
            print(f"{case.name} is held out; pass --held-out to score it (once, at the end)", file=sys.stderr)
            return 2
        workdir = args.workdir or default_workdir()
        workdir.mkdir(parents=True, exist_ok=True)
        out = evaluate(case, args.runs, workdir, baseline_only=args.baseline_only,
                       issue_file=args.issue_file, effort=args.effort)
        print(json.dumps(out, indent=2))
        if args.baseline_only:
            return 0 if out["baseline_valid"] else 1
        return 0 if out.get("passed") else 1
    finally:
        tracing.shutdown()


if __name__ == "__main__":
    sys.exit(main())
