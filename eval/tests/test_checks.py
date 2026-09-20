"""Checks are the only impure grader here, so what they do with a failure,
a crash and a timeout is pinned down rather than assumed."""

import tempfile
import unittest
from pathlib import Path

from taskcut_eval import metrics, workload


def _workload(*checks):
    return workload.Workload(
        name="w", description="", source=workload.Source(kind="generated"),
        files=(), step_template="{file}", probes=(), checks=checks,
    )


class RunChecks(unittest.TestCase):
    def setUp(self):
        self.space = Path(tempfile.mkdtemp())
        (self.space / "present.txt").write_text("hello\n")

    def test_exit_zero_passes_and_output_is_kept(self):
        w = _workload(workload.Check("c", "the file is there", "cat present.txt"))
        result = metrics.run_checks(w, self.space)[0]
        self.assertTrue(result.passed)
        self.assertIn("hello", result.detail)

    def test_exit_nonzero_fails(self):
        w = _workload(workload.Check("c", "a file that is not there", "cat absent.txt"))
        result = metrics.run_checks(w, self.space)[0]
        self.assertFalse(result.passed)
        self.assertTrue(result.detail)

    def test_it_runs_in_the_workspace_not_the_repository(self):
        # A check that ran in the wrong directory would grade the benchmark's
        # own source instead of the work, and would mostly pass while doing it.
        w = _workload(workload.Check("c", "cwd is the workspace", "test -f present.txt"))
        self.assertTrue(metrics.run_checks(w, self.space)[0].passed)

    def test_a_negated_command_is_a_check_that_something_is_absent(self):
        w = _workload(workload.Check("c", "no such file", "! test -f absent.txt"))
        self.assertTrue(metrics.run_checks(w, self.space)[0].passed)

    def test_the_kind_is_carried_through(self):
        w = _workload(workload.Check("c", "d", "true", kind="supersession"))
        self.assertEqual(metrics.run_checks(w, self.space)[0].kind, "supersession")

    def test_a_workload_with_no_checks_produces_none(self):
        self.assertEqual(metrics.run_checks(_workload(), self.space), [])


if __name__ == "__main__":
    unittest.main()
