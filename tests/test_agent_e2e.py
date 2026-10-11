"""End to end runs of the agent loop against a scripted stand-in for the Anthropic client.

The fake returns real anthropic BetaMessage objects through the same
client.beta.messages.stream(...) context manager the agent uses, so the
harness gates, the pytest runs and the files the run writes are all real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from anthropic.types.beta import BetaMessage, BetaTextBlock, BetaToolUseBlock, BetaUsage

from wincheck.agent import Agent
from wincheck.tools import REPRODUCE, Workspace

BUGGY = 'import os\n\n\ndef join(a, b):\n    return a + "/" + b\n'
REPRO = (
    "import pathjoin\n\n\n"
    "def test_join_uses_os_sep(monkeypatch):\n"
    '    monkeypatch.setattr(pathjoin.os, "sep", "\\\\")\n'
    '    assert pathjoin.join("a", "b") == "a" + pathjoin.os.sep + "b"\n'
)
PASSING = 'import pathjoin\n\n\ndef test_join_slash():\n    assert pathjoin.join("a", "b") == "a/b"\n'
REPRO_ID = "tests/test_pathjoin.py::test_join_uses_os_sep"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pathjoin.py").write_text(BUGGY, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "commit", "-q", "-m", "init")
    return root


class _Stream:
    def __init__(self, msg: BetaMessage):
        self._msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self) -> BetaMessage:
        return self._msg


class FakeClient:
    """Answers each model call with the next scripted list of tool calls."""

    def __init__(self, script: list[list[tuple[str, dict]]]):
        self.script = list(script)
        self.calls: list[dict] = []
        self.beta = self
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["tools"] and kwargs["messages"][-1]["role"] == "user"
        if not self.script:
            raise AssertionError("the agent asked for more turns than were scripted")
        n = len(self.calls)
        uses = self.script.pop(0)
        content = [BetaTextBlock(type="text", text=f"turn {n}")] + [
            BetaToolUseBlock(type="tool_use", id=f"toolu_{n}_{i}", name=name, input=args)
            for i, (name, args) in enumerate(uses)
        ]
        return _Stream(BetaMessage(id=f"msg_{n}", type="message", role="assistant", model=kwargs["model"],
                                   content=content, stop_reason="tool_use", stop_sequence=None,
                                   usage=BetaUsage(input_tokens=100, output_tokens=10)))

    def tool_results(self) -> list[dict]:
        """Every tool_result the agent sent back, in order."""
        last = self.calls[-1]["messages"]
        return [b for m in last if m["role"] == "user" and isinstance(m["content"], list)
                for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]


def run(project: Path, tmp_path: Path, script, **kwargs) -> tuple[Agent, FakeClient]:
    client = FakeClient(script)
    ws = Workspace(project, sys.executable, env=dict(os.environ))
    agent = Agent(ws, "join() uses '/' instead of os.sep on Windows", tmp_path / "run", client=client, **kwargs)
    agent.run()
    return agent, client


def test_fixed_end_to_end(project, tmp_path):
    agent, client = run(project, tmp_path, [
        [("read_file", {"path": "pathjoin.py"})],
        [("start_reproduction", {"plan": "test join() with a Windows separator"})],
        [("write_file", {"path": "tests/test_pathjoin.py", "content": REPRO})],
        [("submit_reproduction", {"test_ids": [REPRO_ID], "explanation": "join hard-codes '/'"})],
        [("edit_file", {"path": "pathjoin.py", "old": 'a + "/" + b', "new": "a + os.sep + b"})],
        [("submit_fix", {"summary": "use os.sep"})],
    ])
    r = agent.result
    assert r.status == "fixed", r.reason
    assert r.repro_tests == [REPRO_ID] and r.fix_attempts == 1 and r.turns == 6
    assert not client.script
    assert not any(t.get("is_error") for t in client.tool_results())

    transcript = [json.loads(line) for line in (tmp_path / "run" / "transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    notes = [e["harness"] for e in transcript if "harness" in e]
    accepted = next(n for n in notes if n.startswith("Reproduction accepted"))
    assert f"FAILED  {REPRO_ID}" in accepted  # failed before the fix
    assert notes[-1].startswith("Fix verified") and f"PASSED  {REPRO_ID}" in notes[-1]  # passes after
    assert sum("turn" in e for e in transcript) == 6

    patch = (tmp_path / "run" / "fix.patch").read_text(encoding="utf-8")
    assert "+    return a + os.sep + b" in patch and "tests/test_pathjoin.py" in patch
    assert json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))["status"] == "fixed"


def test_fix_before_reproduction_is_refused(project, tmp_path):
    agent, client = run(project, tmp_path, [
        [("edit_file", {"path": "pathjoin.py", "old": 'a + "/" + b', "new": "a + os.sep + b"})],
        [("start_reproduction", {"plan": "skip ahead"})],
        [("write_file", {"path": "pathjoin.py", "content": "import os\njoin = os.path.join\n"}),
         ("submit_fix", {"summary": "done"})],
        [("give_up", {"reason": "not allowed to fix yet"})],
    ])
    results = client.tool_results()
    assert [bool(r.get("is_error")) for r in results] == [True, False, True, True, False]
    assert "Call start_reproduction first" in results[0]["content"]
    assert "not a test file" in results[2]["content"]
    assert "only valid during the fix phase" in results[3]["content"]
    assert (project / "pathjoin.py").read_text(encoding="utf-8") == BUGGY
    assert agent.result.status == "no_repro" and agent.result.fix_attempts == 0
    assert (tmp_path / "run" / "fix.patch").read_text(encoding="utf-8") == ""


def test_passing_reproduction_is_rejected(project, tmp_path):
    agent, client = run(project, tmp_path, [
        [("start_reproduction", {"plan": "test join"})],
        [("write_file", {"path": "tests/test_pathjoin.py", "content": PASSING})],
        [("submit_reproduction", {"test_ids": ["tests/test_pathjoin.py::test_join_slash"], "explanation": "?"})],
        [("edit_file", {"path": "pathjoin.py", "old": 'a + "/" + b', "new": "a + os.sep + b"})],
        [("give_up", {"reason": "cannot reproduce"})],
    ])
    assert agent.ws.phase == REPRODUCE  # never reached the fix phase
    assert agent.result.repro_tests == [] and agent.result.status == "no_repro"
    notes = [b["text"] for m in client.calls[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)
             for b in m["content"] if b.get("type") == "text"]
    assert any(n.startswith("Reproduction rejected") and "PASSED  tests/test_pathjoin.py::test_join_slash" in n for n in notes)
    assert "not a test file" in client.tool_results()[-2]["content"]
    assert (project / "pathjoin.py").read_text(encoding="utf-8") == BUGGY


def test_give_up_leaves_no_patch(project, tmp_path):
    agent, client = run(project, tmp_path, [
        [("read_file", {"path": "pathjoin.py"})],
        [("give_up", {"reason": "this machine is not Windows"})],
    ])
    assert agent.result.status == "gave_up" and agent.result.reason == "this machine is not Windows"
    assert agent.result.turns == 2 and not client.script
    assert (tmp_path / "run" / "fix.patch").read_text(encoding="utf-8") == ""
    assert _git(project, "status", "--porcelain") == ""


REPRODUCED = [
    [("start_reproduction", {"plan": "test join"})],
    [("write_file", {"path": "tests/test_pathjoin.py", "content": REPRO})],
    [("submit_reproduction", {"test_ids": [REPRO_ID], "explanation": "join hard-codes '/'"})],
]


def test_fix_that_does_not_work_is_not_accepted(project, tmp_path):
    agent, _ = run(project, tmp_path, REPRODUCED + [
        [("edit_file", {"path": "pathjoin.py", "old": 'a + "/" + b', "new": 'a + "/" + b  # fixed?'})],
        [("submit_fix", {"summary": "looks fixed"})],
    ], max_fix_attempts=1)
    assert agent.result.status == "unverified" and agent.result.fix_attempts == 1
    assert f"FAILED  {REPRO_ID}" in agent.result.reason


def test_test_files_changed_during_fix_are_restored(project, tmp_path):
    # run_command is not phase-gated, so the harness must catch this at verification
    cmd = f"\"{sys.executable}\" -c \"open('tests/test_pathjoin.py', 'w').write('def test_join_uses_os_sep(): pass')\""
    agent, client = run(project, tmp_path, REPRODUCED + [
        [("run_command", {"command": cmd})],
        [("submit_fix", {"summary": "the test passes now"})],
    ], max_fix_attempts=1)
    assert client.tool_results()[-2]["content"].startswith("exit code 0")
    assert agent.result.status == "unverified"
    assert "restored: tests/test_pathjoin.py" in agent.result.reason
    assert (project / "tests" / "test_pathjoin.py").read_text(encoding="utf-8") == REPRO
