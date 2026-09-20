"""The two things `drift` added: a probe that can be wrong, and a rule checked
against the work rather than after it."""

import unittest

from taskcut_eval import metrics, transcript, workload


def turn(prompt, texts=(), tools=()):
    t = transcript.Turn(prompt=prompt)
    t.requests = [transcript.Request(1, 1, 1, 1)]
    t.texts = list(texts)
    t.tools = list(tools)
    return t


class Rejection(unittest.TestCase):
    """Without this a superseded value cannot be graded: an answer naming the
    old value and the new one matches every expectation and is useless."""

    def setUp(self):
        self.probe = workload.Probe("S1", workload.KIND_SUPERSEDED, "what is it?", ("7500",), ("3000",))

    def test_the_current_value_alone_is_correct(self):
        self.assertEqual(self.probe.grade("7500"), (1, 1))
        self.assertEqual(self.probe.rejected("7500"), [])

    def test_naming_the_superseded_value_too_is_not(self):
        self.assertEqual(self.probe.grade("7500, up from 3000"), (1, 1))
        self.assertEqual(self.probe.rejected("7500, up from 3000"), ["3000"])

    def test_a_rejected_answer_is_incorrect_however_well_it_matched(self):
        w = _workload(probes=(self.probe,))
        t = transcript.Transcript(path=None, turns=[turn("what is it?", texts=["7500, up from 3000"])])
        result = metrics.probe_results(t, w)[0]
        self.assertEqual(result.matched, 1)
        self.assertFalse(result.correct)

    def test_a_probe_with_nothing_to_reject_behaves_as_before(self):
        plain = workload.Probe("H", workload.KIND_HEADLINE, "q", ("alpha",))
        self.assertEqual(plain.rejected("alpha and 3000"), [])


class ConstraintDrift(unittest.TestCase):
    def setUp(self):
        self.constraint = workload.Constraint("registry", "uses the registry id", r"SVC-\d{4}")

    def test_the_series_is_per_step_and_in_order(self):
        w = _workload(files=("a.py", "b.py", "c.py"), constraints=(self.constraint,))
        steps = w.steps()
        t = transcript.Transcript(path=None, turns=[
            turn(steps[0], texts=["SVC-1040 is owned by ravi"]),
            turn(steps[1], texts=["b.py is owned by mei"]),
            turn(steps[2], texts=["SVC-1054 is owned by tomas"]),
        ])
        drift = metrics.constraint_drift(t, w)[0]
        self.assertEqual(drift.per_step, (True, False, True))
        self.assertEqual(drift.held, 2)
        self.assertEqual(drift.first_lapse, 2)

    def test_a_rule_never_broken_reports_no_lapse(self):
        w = _workload(files=("a.py",), constraints=(self.constraint,))
        t = transcript.Transcript(path=None, turns=[turn(w.steps()[0], texts=["SVC-1040"])])
        self.assertIsNone(metrics.constraint_drift(t, w)[0].first_lapse)

    def test_a_step_with_no_answer_counts_as_a_lapse(self):
        # Silence is not compliance: a step whose turn is missing did not apply
        # the rule, and scoring it as held would hide exactly what is sought.
        w = _workload(files=("a.py", "b.py"), constraints=(self.constraint,))
        t = transcript.Transcript(path=None, turns=[turn(w.steps()[0], texts=["SVC-1040"])])
        self.assertEqual(metrics.constraint_drift(t, w)[0].per_step, (True, False))

    def test_matching_ignores_case(self):
        w = _workload(files=("a.py",), constraints=(workload.Constraint("v", "version", r"v3\.7\.0"),))
        t = transcript.Transcript(path=None, turns=[turn(w.steps()[0], texts=["schema V3.7.0"])])
        self.assertEqual(metrics.constraint_drift(t, w)[0].per_step, (True,))

    def test_a_workload_with_no_constraints_reports_none(self):
        w = _workload(files=("a.py",))
        self.assertEqual(metrics.constraint_drift(transcript.Transcript(path=None), w), [])


def _workload(files=("a.py",), probes=(), constraints=()):
    return workload.Workload(
        name="w", description="", source=workload.Source(kind="generated"),
        files=files, step_template="Step {n} of {total}: read {file}.",
        probes=probes, briefing="the rules", constraints=constraints,
    )


if __name__ == "__main__":
    unittest.main()
