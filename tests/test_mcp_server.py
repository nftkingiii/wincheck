"""The MCP server reads the CLI's JSON even with log lines around it."""

import json

import pytest

pytest.importorskip("mcp")

from wincheck.mcp_server import _last_json  # noqa: E402

RESULT = {"case": "click-3277", "passed": True, "score": {"targets": {"t::a": "PASSED"}, "regressions": []}}


def test_json_followed_by_neatlogs_shutdown_line():
    stdout = ("[wincheck] neatlogs export on\n" + json.dumps(RESULT, indent=2)
              + "\n2026-10-11 07:01:04 - neatlogs - INFO - Neatlogs SDK shutdown complete\n")
    assert _last_json(stdout) == RESULT


def test_json_only_and_no_json():
    assert _last_json(json.dumps(RESULT, indent=2) + "\n") == RESULT
    assert _last_json("[wincheck] neatlogs export off\n") is None
