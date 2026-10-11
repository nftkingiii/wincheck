"""Which test ids count towards an eval case's score."""

import sys
from pathlib import Path

from wincheck.evals import CASES, Case, Project, _counted


def project(case: Case) -> Project:
    return Project(case, Path("."), sys.executable, {}, list(case.test_files))


def test_inner_pytest_tmp_tests_are_not_counted():
    # PR #8: pytest's own suite runs an inner pytest whose summary lines for
    # tests in temp dirs land in the captured output and were counted as targets.
    p = project(CASES["pytest-pathlib"])
    assert _counted(p, "testing/test_pathlib.py::TestImportPath::test_x")
    assert _counted(p, r"testing\test_pathlib.py::test_y")
    assert not _counted(p, r"..\tmp\pytest-of-runner\pytest-0\test_a0\test_a.py::test")
    assert not _counted(p, "../tmp/pytest-of-runner/pytest-0/test_a0/test_a.py::test")
    assert not _counted(p, "testing/test_other.py::test_z")


def test_exclude_is_respected():
    p = project(CASES["tox-3222"])
    assert _counted(p, "tests/config/loader/test_str_convert.py::test_str_convert_ok[x]")
    assert not _counted(p, "tests/config/loader/test_str_convert.py::test_setenv_path_not_overwritten")


def test_cases_are_well_formed():
    assert len(CASES) == 6
    assert {c.split for c in CASES.values()} == {"dev", "held_out"}
    for c in CASES.values():
        assert len(c.fix) == 40 and c.test_files
