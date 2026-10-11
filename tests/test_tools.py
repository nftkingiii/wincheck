"""Phase gates and secret scrubbing in the tool workspace."""

import sys

import pytest

from wincheck.tools import FIX, READ, REPRODUCE, SECRET_VARS, ToolError, Workspace, scrub


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    return Workspace(tmp_path, sys.executable, env={})


def test_nothing_can_be_written_while_reading(ws):
    assert ws.phase == READ
    with pytest.raises(ToolError):
        ws.write_file("tests/test_new.py", "")
    with pytest.raises(ToolError):
        ws.write_file("pkg/mod.py", "x = 2\n")


def test_reproduce_refuses_source_files(ws):
    ws.phase = REPRODUCE
    with pytest.raises(ToolError, match="not a test file"):
        ws.write_file("pkg/mod.py", "x = 2\n")
    with pytest.raises(ToolError, match="not a test file"):
        ws.edit_file("pkg/mod.py", "x = 1", "x = 2")
    assert (ws.root / "pkg" / "mod.py").read_text(encoding="utf-8") == "x = 1\n"
    ws.write_file("tests/test_new.py", "def test_y():\n    pass\n")
    ws.write_file("pkg/test_inline.py", "")
    ws.write_file("conftest.py", "")


def test_fix_refuses_test_files(ws):
    ws.phase = FIX
    with pytest.raises(ToolError, match="frozen"):
        ws.write_file("tests/test_mod.py", "")
    with pytest.raises(ToolError, match="frozen"):
        ws.edit_file("tests/test_mod.py", "pass", "assert 0")
    with pytest.raises(ToolError, match="frozen"):
        ws.write_file("pkg/mod_test.py", "")
    ws.edit_file("pkg/mod.py", "x = 1", "x = 2")
    assert (ws.root / "pkg" / "mod.py").read_text(encoding="utf-8") == "x = 2\n"


@pytest.mark.parametrize("phase", [READ, REPRODUCE, FIX])
def test_reads_work_in_every_phase(ws, phase):
    ws.phase = phase
    assert "x = 1" in ws.read_file("pkg/mod.py")
    assert "mod.py" in ws.list_dir("pkg")
    assert "pkg/mod.py:1:" in ws.search(r"x = 1")


@pytest.mark.parametrize("phase", [READ, REPRODUCE, FIX])
def test_paths_outside_the_workspace_are_refused(ws, tmp_path, phase):
    ws.phase = phase
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    for path in ("../outside.txt", str(outside)):
        with pytest.raises(ToolError, match="outside the project"):
            ws.read_file(path)
    with pytest.raises(ToolError):
        ws.write_file("../tests/test_escape.py", "")
    assert not (tmp_path.parent / "tests" / "test_escape.py").exists()


def test_commands_and_tests_wait_for_reproduction(ws):
    with pytest.raises(ToolError):
        ws.run_command("echo hi")
    with pytest.raises(ToolError):
        ws.run_tests(["tests/test_mod.py::test_x"])


def test_scrub_removes_every_secret_case_insensitively():
    env = {}
    for i, name in enumerate(SECRET_VARS):
        env[name] = "s"
        env[name.lower() if i % 2 else name.title()] = "s"
    env.update({"PATH": "/bin", "HOME": "/home/me", "ANTHROPIC_BASE_URL": "x", "MY_TOKEN_NAME": "y"})
    assert scrub(env) == {"PATH": "/bin", "HOME": "/home/me", "ANTHROPIC_BASE_URL": "x", "MY_TOKEN_NAME": "y"}


def test_workspace_env_is_scrubbed(tmp_path):
    ws = Workspace(tmp_path, sys.executable, env={"ANTHROPIC_API_KEY": "k", "neatlogs_api_key": "k", "PATH": "/bin"})
    assert ws.env == {"PATH": "/bin"}
