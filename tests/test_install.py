import subprocess
from pathlib import Path

from wincheck import evals


def _capture(monkeypatch, fail_uv=False):
    calls = []

    def fake_run(cmd, cwd, env=None):
        calls.append(cmd)
        if fail_uv and "uv" in Path(cmd[0]).name:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(evals, "_run", fake_run)
    return calls


def test_uses_uv_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(evals.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.delenv("WINCHECK_NO_UV", raising=False)
    calls = _capture(monkeypatch)
    evals.install_deps("py", tmp_path, ("-e", ".", "--group", "test"))
    assert calls == [["/usr/bin/uv", "pip", "install", "--python", "py", "--quiet", "-e", ".", "--group", "test"]]


def test_falls_back_to_pip_when_uv_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(evals.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.delenv("WINCHECK_NO_UV", raising=False)
    calls = _capture(monkeypatch, fail_uv=True)
    evals.install_deps("py", tmp_path, ("-e", "."))
    assert calls[1:] == [["py", "-m", "pip", "install", "--quiet", "--upgrade", "pip>=25.1"],
                         ["py", "-m", "pip", "install", "--quiet", "-e", "."]]


def test_uses_pip_without_uv(monkeypatch, tmp_path):
    monkeypatch.setattr(evals.shutil, "which", lambda name: None)
    calls = _capture(monkeypatch)
    evals.install_deps("py", tmp_path, ("-e", "."))
    assert [c[1:4] for c in calls] == [["-m", "pip", "install"], ["-m", "pip", "install"]]
