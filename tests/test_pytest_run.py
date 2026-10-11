"""Reading pytest's -rA summary back into per-test outcomes."""

from wincheck.pytest_run import PytestResult, parse_summary

SUMMARY = """\
============================= short test summary info ==============================
PASSED tests/test_a.py::test_ok
FAILED tests/test_a.py::test_bad - AssertionError: assert 1 == 2
PASSED tests/test_a.py::test_teardown
ERROR tests/test_a.py::test_teardown - RuntimeError: boom in teardown
SKIPPED [1] tests/test_a.py:12: needs Windows
ERROR tests/test_b.py - ImportError: no module named x
"""


def test_parse_summary():
    out = parse_summary(SUMMARY)
    assert out["tests/test_a.py::test_ok"] == "PASSED"
    assert out["tests/test_a.py::test_bad"] == "FAILED"
    assert out["tests/test_a.py::test_teardown"] == "ERROR"


def test_skipped_and_collection_errors_are_ignored():
    out = parse_summary(SUMMARY)
    assert not any("test_b.py" in k for k in out)
    assert not any(k.startswith("[1]") for k in out)
    assert "SKIPPED" not in out.values()


def test_error_after_pass_stays_error_in_either_order():
    out = parse_summary("ERROR t/test_x.py::test_y - boom\nPASSED t/test_x.py::test_y\n")
    assert out == {"t/test_x.py::test_y": "ERROR"}


def test_outcome_normalizes_windows_backslash_ids():
    res = PytestResult(1, parse_summary(r"FAILED tests\sub\test_w.py::test_path - AssertionError" + "\n"))
    assert res.outcome("tests/sub/test_w.py::test_path") == "FAILED"
    assert res.outcome(r"tests\sub\test_w.py::test_path") == "FAILED"
    # only the path part is normalized, not the test name
    res2 = PytestResult(0, {"tests/test_w.py::test_p[a\\b]": "PASSED"})
    assert res2.outcome("tests\\test_w.py::test_p[a\\b]") == "PASSED"
    assert res.outcome("tests/sub/test_w.py::test_other") == "MISSING"
