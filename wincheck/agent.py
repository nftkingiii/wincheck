"""The Wincheck agent: read the issue, reproduce it, fix it, verify the fix.

The model drives each phase with tools; the harness owns the gates between
phases. A reproduction is only accepted when the harness itself sees every
submitted test fail, and a fix is only accepted when those tests pass and the
test files they live in have no new failures. Without an accepted
reproduction, nothing outside the test files can be changed.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import anthropic

from . import tracing
from .pytest_run import clip, run_pytest
from .tools import FIX, READ, REPRODUCE, TOOL_SPECS, ToolError, Workspace, build_dispatch, is_test_path, validate_input

MODEL = "claude-opus-5-5"
SPECS_BY_NAME = {s["name"]: s for s in TOOL_SPECS}

SYSTEM = """You are Wincheck, an engineer who fixes Windows-specific bugs in Python projects.

You are given an issue report and a checkout of the project at the commit where the bug exists. You work in three phases, and a harness enforces the gates between them:

1. read - explore the code and the issue. Nothing can be written or run yet. Call start_reproduction when you understand the bug well enough to test it.
2. reproduce - write pytest tests that fail because of the bug, then call submit_reproduction with their node ids. Only test files can be written. The harness runs the tests itself and accepts the reproduction only if every one of them fails on this machine. Prefer adding a focused test to the project's existing test file for that area, written in the project's style, so it can stay in the codebase as a regression test. The test must fail for the reason in the issue, not because of a typo or an import error.
3. fix - change the project's source so the reproduction passes. Test files are frozen. Call submit_fix when done; the harness re-runs the reproduction (all must pass) and the whole test files they live in (no test that passed before may fail now). If verification fails you get the output and can try again.

If the bug does not reproduce on this machine after a genuine attempt, call give_up and explain what you tried. Never patch code without a reproduction.

Keep the fix as small as the bug allows and match the surrounding code. Think about how Windows differs: path separators and drive letters, CRLF line endings and text-mode newline translation, file locking (an open file cannot be deleted or replaced), case-insensitive paths, the console encoding, MAX_PATH, process spawning and signals, and shell quoting.
"""


@dataclass
class AgentResult:
    status: str = "running"  # fixed | unverified | no_repro | gave_up | error
    reason: str = ""
    repro_tests: list[str] = field(default_factory=list)
    repro_explanation: str = ""
    fix_summary: str = ""
    fix_attempts: int = 0
    diff: str = ""
    turns: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    platform: str = field(default_factory=lambda: f"{platform.system()} {platform.release()} / Python {platform.python_version()}")


class Agent:
    def __init__(
        self,
        ws: Workspace,
        issue: str,
        run_dir: Path,
        model: str = MODEL,
        effort: str = "high",
        max_turns_per_phase: int = 40,
        max_fix_attempts: int = 3,
        client: anthropic.Anthropic | None = None,
    ):
        self.ws = ws
        self.issue = issue
        self.run_dir = run_dir
        self.model = model
        self.effort = effort
        self.max_turns = max_turns_per_phase
        self.max_fix_attempts = max_fix_attempts
        self.client = client or anthropic.Anthropic(max_retries=4)
        self.tools = build_dispatch(ws)
        self.messages: list[dict[str, Any]] = []
        self.result = AgentResult()
        self.test_snapshot: dict[str, bytes | None] = {}
        self.baseline: dict[str, str] = {}
        self._log = None

    # -- top level -------------------------------------------------------
    @tracing.span(kind="WORKFLOW", name="wincheck_run", capture_input=False)
    def run(self) -> AgentResult:
        start = time.monotonic()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._log = open(self.run_dir / "transcript.jsonl", "w", encoding="utf-8")
        self.messages.append({"role": "user", "content": self._opening()})
        try:
            if self._read_phase() and self._reproduce_phase():
                self._fix_phase()
        except _Stop as stop:
            self.result.status, self.result.reason = stop.status, stop.reason
        except anthropic.APIError as exc:
            self.result.status, self.result.reason = "error", f"API error: {exc}"
        finally:
            self.result.diff = self._diff()
            self.result.seconds = round(time.monotonic() - start, 1)
            self._log.close()
            (self.run_dir / "result.json").write_text(json.dumps(asdict(self.result), indent=2), encoding="utf-8")
            (self.run_dir / "fix.patch").write_text(self.result.diff, encoding="utf-8")
        return self.result

    def _opening(self) -> str:
        return (
            f"Machine: {self.result.platform} ({sys.platform}). Shell for run_command: "
            f"{'cmd.exe' if sys.platform == 'win32' else 'sh'}. The project's virtualenv is active for "
            f"run_command and run_tests.\n\nPhase: read.\n\n<issue>\n{self.issue}\n</issue>"
        )

    # -- phases ----------------------------------------------------------
    @tracing.span(kind="AGENT", name="read_issue", capture_input=False, role="reader", goal="Understand the bug from the issue and the code")
    def _read_phase(self) -> bool:
        self.ws.phase = READ
        kind, _ = self._converse(READ, {"start_reproduction"})
        if kind == "give_up":
            return False
        self.ws.phase = REPRODUCE
        self._note("Phase: reproduce. You can now write test files and run commands and tests.")
        return True

    @tracing.span(kind="AGENT", name="reproduce", capture_input=False, role="reproducer", goal="Write tests that fail because of the bug")
    def _reproduce_phase(self) -> bool:
        while True:
            kind, data = self._converse(REPRODUCE, {"submit_reproduction"})
            if kind == "give_up":
                self.result.status = "no_repro"
                return False
            ok, report = self._check_reproduction(data["test_ids"])
            if ok:
                self.result.repro_tests = data["test_ids"]
                self.result.repro_explanation = data["explanation"]
                self.ws.phase = FIX
                self._note(f"Reproduction accepted.\n{report}\n\nPhase: fix. Test files are now frozen; change the source.")
                return True
            self._note(f"Reproduction rejected: every submitted test must FAIL.\n{report}")

    @tracing.span(kind="AGENT", name="fix_and_verify", capture_input=False, role="fixer", goal="Make the reproduction pass without regressions")
    def _fix_phase(self) -> None:
        while True:
            kind, data = self._converse(FIX, {"submit_fix"})
            if kind == "give_up":
                return
            self.result.fix_attempts += 1
            self.result.fix_summary = data["summary"]
            ok, report = self._verify()
            if ok:
                self.result.status = "fixed"
                self._note(f"Fix verified.\n{report}", final=True)
                return
            if self.result.fix_attempts >= self.max_fix_attempts:
                self.result.status, self.result.reason = "unverified", report
                return
            self._note(f"Verification failed (attempt {self.result.fix_attempts} of {self.max_fix_attempts}).\n{report}")

    # -- harness gates ---------------------------------------------------
    @tracing.span(kind="TOOL", name="check_reproduction", capture_input=False, tool_name="check_reproduction")
    def _check_reproduction(self, test_ids: list[str]) -> tuple[bool, str]:
        res = run_pytest(self.ws.python, self.ws.root, test_ids, env=self.ws.env)
        outcomes = {t: res.outcome(t) for t in test_ids}
        lines = "\n".join(f"{o:7} {t}" for t, o in outcomes.items())
        if not all(o == "FAILED" for o in outcomes.values()):
            return False, f"{lines}\n\n--- output ---\n{clip(res.output, 15000)}"
        # Freeze test files and record how their whole files behave before the fix.
        self.test_snapshot = {p: self._read_bytes(p) for p in self._changed_test_files()}
        files = sorted({t.split("::", 1)[0] for t in test_ids})
        base = run_pytest(self.ws.python, self.ws.root, files, env=self.ws.env)
        self.baseline = base.outcomes
        return True, lines

    @tracing.span(kind="TOOL", name="verify_fix", capture_input=False, tool_name="verify_fix")
    def _verify(self) -> tuple[bool, str]:
        tampered = self._restore_tests()
        if tampered:
            return False, "These test files were changed during the fix phase and have been restored: " + ", ".join(tampered)
        files = sorted({t.split("::", 1)[0] for t in self.result.repro_tests})
        res = run_pytest(self.ws.python, self.ws.root, files, env=self.ws.env)
        repro = {t: res.outcome(t) for t in self.result.repro_tests}
        regressions = [
            t for t, before in self.baseline.items()
            if before == "PASSED" and res.outcome(t) not in ("PASSED", "XFAIL") and t not in repro
        ]
        lines = [f"{o:7} {t}" for t, o in repro.items()]
        if regressions:
            lines.append("New failures: " + ", ".join(regressions))
        ok = all(o == "PASSED" for o in repro.values()) and not regressions
        report = "\n".join(lines)
        if not ok:
            report += f"\n\n--- output ---\n{clip(res.output, 15000)}"
        return ok, report

    # -- conversation ----------------------------------------------------
    def _converse(self, phase: str, exits: set[str]) -> tuple[str, dict[str, Any]]:
        """Run model turns until it calls one of `exits` (or give_up)."""
        nudges = 0
        for _ in range(self.max_turns):
            msg = self._call_model()
            self.messages.append({"role": "assistant", "content": msg.content})
            if msg.stop_reason == "refusal":
                raise _Stop("error", f"model refused: {getattr(msg, 'stop_details', None)}")
            uses = [b for b in msg.content if b.type == "tool_use"]
            if not uses:
                nudges += 1
                if nudges > 3:
                    raise _Stop("error", f"model stopped calling tools in phase {phase}")
                self._note(f"You are in the {phase} phase. Continue with tools; finish the phase with {' or '.join(sorted(exits))}, or call give_up.")
                continue
            results = [self._run_tool(b, truncated=msg.stop_reason == "max_tokens") for b in uses]
            self.messages.append({"role": "user", "content": results})
            sub, self.ws.submission = self.ws.submission, None
            if sub and (sub[0] in exits or sub[0] == "give_up"):
                if sub[0] == "give_up":
                    self.result.status, self.result.reason = "gave_up", sub[1]["reason"]
                return sub
        raise _Stop("error", f"turn limit reached in phase {phase}")

    def _call_model(self):
        self.result.turns += 1
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            system=SYSTEM,
            tools=TOOL_SPECS,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            self.result.usage[key] = self.result.usage.get(key, 0) + (getattr(msg.usage, key, 0) or 0)
        self._record({"turn": self.result.turns, "phase": self.ws.phase, "stop_reason": msg.stop_reason,
                      "content": [b.model_dump(mode="json") for b in msg.content]})
        return msg

    def _run_tool(self, block, truncated: bool) -> dict[str, Any]:
        def result(text: str, error: bool = False) -> dict[str, Any]:
            self._record({"tool": block.name, "input": block.input if isinstance(block.input, dict) else str(block.input),
                          "error": error, "result": text[:4000]})
            out = {"type": "tool_result", "tool_use_id": block.id, "content": text}
            if error:
                out["is_error"] = True
            return out

        spec = SPECS_BY_NAME.get(block.name)
        if spec is None:
            return result(f"unknown tool {block.name}", True)
        if truncated:
            return result("Your response hit the output limit and this call was cut off. Send it again, smaller if possible.", True)
        problem = validate_input(spec, block.input)
        if problem:
            return result(f"invalid input: {problem}", True)
        try:
            return result(self.tools[block.name](**block.input))
        except ToolError as exc:
            return result(str(exc), True)
        except Exception as exc:  # a tool bug should not end the run
            return result(f"{type(exc).__name__}: {exc}", True)

    def _note(self, text: str, final: bool = False) -> None:
        """Tell the model what the harness decided, appending to the last user turn."""
        self._record({"harness": text})
        if final:
            return
        last = self.messages[-1]
        if last["role"] == "user" and isinstance(last["content"], list):
            last["content"].append({"type": "text", "text": text})
        else:
            self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

    def _record(self, entry: dict[str, Any]) -> None:
        if self._log:
            self._log.write(json.dumps(entry, default=str) + "\n")
            self._log.flush()

    # -- git helpers -----------------------------------------------------
    def _git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.ws.root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout

    def _changed_test_files(self) -> list[str]:
        files = []
        for line in self._git("status", "--porcelain", "--untracked-files=all").splitlines():
            path = line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if is_test_path(path):
                files.append(path)
        return files

    def _read_bytes(self, rel: str) -> bytes | None:
        p = self.ws.root / rel
        return p.read_bytes() if p.is_file() else None

    def _restore_tests(self) -> list[str]:
        tampered = []
        for rel in set(self._changed_test_files()) | set(self.test_snapshot):
            if rel not in self.test_snapshot:
                # a test file that was not touched during reproduction: put it back
                self._git("checkout", "--", rel)
                if (self.ws.root / rel).exists() and self._git("ls-files", rel).strip() == "":
                    (self.ws.root / rel).unlink()
                tampered.append(rel)
                continue
            want = self.test_snapshot[rel]
            if self._read_bytes(rel) != want:
                tampered.append(rel)
                if want is not None:
                    (self.ws.root / rel).write_bytes(want)
        return tampered

    def _diff(self) -> str:
        skip = (":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc")
        self._git("add", "-N", "--", ".", *skip)
        return self._git("diff", "--", ".", *skip)


class _Stop(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason
