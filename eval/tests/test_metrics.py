"""The numbers, checked against hand-computed values."""

import shutil
import subprocess
import unittest
from pathlib import Path

from taskcut_eval import metrics, transcript, workload

REPO = Path(__file__).resolve().parents[2]


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


LOG = """\
2026-09-23T14:22:26.120Z [DEBUG] [taskcut] $.ui.log (to debug): context at 36%, step judged the same work [judge sonnet: in=1834 cache_read=0 cache_write=0 out=52 ms=2140]
2026-09-23T14:22:27.001Z [DEBUG] something else entirely: in=999 out=999
2026-09-23T14:22:31.120Z [DEBUG] [taskcut] $.ui.log (to debug): context at 37%, step judged a new piece [judge sonnet: in=2001 cache_read=100 cache_write=40 out=61 ms=1800]
2026-09-23T14:22:40.120Z [DEBUG] [taskcut] $.ui.log (to debug): context at 37%, could not judge the step (api-error 429 rate_limit) [judge sonnet: in=0 cache_read=0 cache_write=0 out=0 ms=300]
2026-09-23T14:22:41.120Z [DEBUG] [taskcut] $.ui.log (to debug): context at 38%, step judged the same work
"""


class Judging(unittest.TestCase):
    def test_every_call_is_summed_answered_or_not(self):
        j = metrics.judging(LOG)
        self.assertEqual((j.calls, j.moved_on, j.unanswered), (3, 1, 1))
        self.assertEqual((j.plain, j.read, j.write, j.output, j.ms), (3835, 100, 40, 113, 4240))
        self.assertEqual(j.model, "sonnet")

    def test_weighted_like_the_session_is(self):
        j = metrics.judging(LOG)
        self.assertAlmostEqual(j.weighted, 3835 + 1.25 * 40 + 0.1 * 100)

    def test_a_line_without_a_record_is_not_a_call_it_can_price(self):
        # A Claude Code that reported no cost: the line is there, the numbers are not.
        self.assertEqual(metrics.judging(LOG.splitlines()[-1]).calls, 0)

    def test_no_log_is_nothing_judged(self):
        self.assertEqual(metrics.judging("").calls, 0)

    @unittest.skipUnless(shutil.which("node"), "node runs the plugin's own formatter")
    def test_reads_what_the_plugin_writes(self):
        # The format is a contract between hooks/spend.ts and this parser:
        # render a line with the plugin's own code and read it back here.
        script = (
            "import { judgementLine } from './hooks/spend.ts';"
            "console.log(judgementLine(52, 'step judged a new piece', 'claude-sonnet-5',"
            " { input_tokens: 7, output_tokens: 8, cache_read_input_tokens: 9, cache_creation_input_tokens: 10 }, 11.6))"
        )
        line = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO, capture_output=True, text=True, check=True).stdout
        j = metrics.judging(f"2026 [DEBUG] [taskcut] $.ui.log (to debug): {line}")
        self.assertEqual((j.calls, j.moved_on, j.model), (1, 1, "claude-sonnet-5"))
        self.assertEqual((j.plain, j.output, j.read, j.write, j.ms), (7, 8, 9, 10, 12))


class ReportReadsTheSidecar(unittest.TestCase):
    """The judge's sums reach the report's cost table, through the command a
    person runs."""

    def test_the_judge_columns_come_from_the_sidecar(self):
        import contextlib
        import io
        import json
        import tempfile

        from taskcut_eval import cli

        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            record = {"type": "assistant", "requestId": "r", "timestamp": "2026-09-23T00:00:00Z",
                      "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                                  "usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}}
            prompt = {"type": "user", "timestamp": "2026-09-23T00:00:00Z", "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}}
            (results / "synthetic--default--sonnet.jsonl").write_text(json.dumps(prompt) + "\n" + json.dumps(record) + "\n")
            (results / "synthetic--off--sonnet.jsonl").write_text(json.dumps(prompt) + "\n" + json.dumps(record) + "\n")
            (results / "synthetic--default--sonnet.judging.json").write_text(json.dumps(vars(metrics.judging(LOG))))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--results", str(results), "report"])
            cost = out.getvalue().split("## Cost", 1)[1].split("\n## ", 1)[0]
            rows = {line.split("|")[1].strip(): line for line in cost.splitlines() if line.startswith("| default") or line.startswith("| off")}
            self.assertIn("3 (sonnet)", rows["default"])
            self.assertIn("3,895", rows["default"])  # 3835 + 1.25 * 40 + 0.1 * 100
            self.assertIn("| -", rows["off"].replace("|  ", "| "))

    def test_runs_json_keeps_the_runs_whose_transcripts_are_not_here(self):
        import contextlib
        import io
        import json
        import tempfile

        from taskcut_eval import cli

        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory)
            (results / "runs.json").write_text(json.dumps({"flask": {"sonnet": {"off": {"requests": 7}}}}))
            prompt = {"type": "user", "timestamp": "2026-09-23T00:00:00Z", "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}}
            (results / "synthetic--off--sonnet.jsonl").write_text(json.dumps(prompt) + "\n")
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--results", str(results), "report"])
            summary = json.loads((results / "runs.json").read_text())
            self.assertEqual(summary["flask"]["sonnet"]["off"], {"requests": 7})
            self.assertIn("off", summary["synthetic"]["sonnet"])


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
