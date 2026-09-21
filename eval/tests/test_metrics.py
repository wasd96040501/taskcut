"""The numbers, checked against hand-computed values."""

import unittest

from taskcut_eval import metrics, transcript, workload


def turn(prompt, requests, texts=(), tools=()):
    t = transcript.Turn(prompt=prompt)
    t.requests = [transcript.Request(*r) for r in requests]
    t.texts = list(texts)
    t.tools = list(tools)
    return t


class Cost(unittest.TestCase):
    def test_weighting_follows_the_published_multipliers(self):
        t = transcript.Transcript(path=None, turns=[turn("a", [(1000, 100, 2, 30)])])
        cost = metrics.cost(t)
        self.assertEqual(cost.weighted, 2 + 1.25 * 100 + 0.1 * 1000)

    def test_the_naive_sum_is_reported_and_is_larger(self):
        t = transcript.Transcript(path=None, turns=[turn("a", [(1000, 100, 2, 30)])])
        cost = metrics.cost(t)
        self.assertGreater(cost.naive, cost.weighted)


class Context(unittest.TestCase):
    def test_a_turn_counts_read_plus_write(self):
        # Read alone makes an arm that cuts look emptier than it is: a cut
        # invalidates the cache, so most of what it carries arrives as a write.
        t = transcript.Transcript(path=None, turns=[turn("a", [(1000, 500, 2, 30), (9999, 0, 0, 0)])])
        self.assertEqual(metrics.prefix_series(t), [1500])

    def test_a_turn_with_no_request_is_skipped(self):
        t = transcript.Transcript(path=None, turns=[turn("unanswered", [])])
        self.assertEqual(metrics.prefix_series(t), [])


class Fidelity(unittest.TestCase):
    def setUp(self):
        self.workload = workload.Workload(
            name="w", description="", source=workload.Source(kind="generated"),
            files=(), step_template="{file}",
            probes=(
                workload.Probe("H1", workload.KIND_HEADLINE, "what is x?", ("alpha",)),
                workload.Probe("I1", workload.KIND_INCIDENTAL, "what is y?", ("beta",)),
            ),
        )

    def test_going_back_to_disk_is_recorded_separately_from_being_right(self):
        t = transcript.Transcript(path=None, turns=[
            turn("what is x?", [(1, 1, 1, 1)], texts=["it is alpha"]),
            turn("what is y?", [(1, 1, 1, 1)], texts=["it is beta"], tools=["Bash", "Bash"]),
        ])
        results = metrics.probe_results(t, self.workload)
        self.assertTrue(all(r.correct for r in results))
        self.assertFalse(results[0].went_to_disk)
        self.assertTrue(results[1].went_to_disk)
        by_kind = metrics.fidelity(results)
        self.assertEqual(by_kind[workload.KIND_INCIDENTAL].tool_calls, 2)
        self.assertEqual(by_kind[workload.KIND_HEADLINE].reread_rate, 0.0)

    def test_a_probe_that_was_never_asked_is_wrong_not_missing(self):
        results = metrics.probe_results(transcript.Transcript(path=None), self.workload)
        self.assertEqual([r.correct for r in results], [False, False])

    def test_grading_needs_every_expectation(self):
        probe = workload.Probe("H", workload.KIND_HEADLINE, "q", ("alpha", "gamma"))
        self.assertEqual(probe.grade("only alpha here"), (1, 2))
        self.assertEqual(probe.grade("ALPHA and GAMMA"), (2, 2))


if __name__ == "__main__":
    unittest.main()


class OneMessage(unittest.TestCase):
    """A job handed over in one message: the benchmark counts how often it had
    to step in, and how often taskcut carried the work on by itself."""

    def setUp(self):
        self.job = workload.Workload(
            name="job", description="", source=workload.Source(kind="generated"), files=("a", "b"),
            step_template="", probes=(), task="do a and b", nudge="Keep going.", done_marker="ALL DONE", max_nudges=3,
        )
        turns = [
            transcript.Turn(prompt="do a and b"),
            transcript.Turn(prompt=f"{transcript.CONTINUE_OPENING}: Continue."),
            transcript.Turn(prompt="Keep going."),
            transcript.Turn(prompt=f"{transcript.CONTINUE_OPENING}: Continue."),
        ]
        self.run = metrics.summarise(transcript.Transcript(path=None, turns=turns), self.job, "on")

    def test_nudges_are_the_benchmark_prompts(self):
        self.assertEqual(self.run.nudges, 1)

    def test_continues_are_taskcut_prompts(self):
        self.assertEqual(self.run.continued, 2)

    def test_a_workload_without_a_task_takes_a_turn_per_file(self):
        self.assertEqual(workload.Workload(name="w", description="", source=workload.Source(kind="generated"),
                                           files=("x",), step_template="{file}", probes=()).task, "")
