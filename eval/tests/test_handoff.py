"""Handoff labels: that the labeller reads the steps the judge replay asks about,
under the same numbers, and that a call made before is not paid for again."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskcut_eval import handoff, replay
from tests.test_replay import SESSION


class Segments(unittest.TestCase):
    def setUp(self):
        self.segs = handoff.segments(SESSION, "s")

    def test_a_compaction_starts_a_segment_and_its_summary_ends_the_one_before(self):
        self.assertEqual(len(self.segs), 2)
        self.assertIn("issue 1 done", self.segs[0].summary)

    def test_steps_are_numbered_as_the_replay_numbers_them(self):
        mark = re.compile(r"^=== #(\d+) \(context \d+%\) ===$")
        numbered = [int(m.group(1)) for seg in self.segs for line in seg.full for m in [mark.match(line)] if m]
        self.assertEqual(numbered, [s["n"] for s in replay.parse(SESSION)["steps"]])

    def test_the_full_text_holds_output_and_the_trail_does_not(self):
        full, trail = "\n".join(self.segs[0].full), "\n".join(self.segs[0].trail)
        self.assertIn("OUTPUT", full)
        self.assertNotIn("OUTPUT", trail)

    def test_a_sub_agent_is_not_read(self):
        self.assertNotIn("a sub-agent", "\n".join(line for seg in self.segs for line in seg.full))


class Jobs(unittest.TestCase):
    def test_only_judged_steps_past_the_floor_are_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in SESSION))
            jobs = handoff.jobs(path, Path(tmp) / "work", floor=0)
            self.assertEqual([n for j in jobs for n in j.steps], replay.judged(replay.parse(SESSION)))
            self.assertEqual(handoff.jobs(path, Path(tmp) / "work", floor=10**9), [])

    def test_a_call_made_before_comes_from_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_text("".join(json.dumps(r) + "\n" for r in SESSION))
            job = handoff.jobs(path, Path(tmp) / "work", floor=0)[0]
            reply = {"result": "\n".join(json.dumps({"step": n, "label": "KEEP", "open": "x", "evidence": "y"}) for n in job.steps),
                     "total_cost_usd": 1.5}
            with mock.patch.object(handoff, "_ask", return_value=reply) as ask:
                first = handoff.run(job, Path(tmp) / "cache")
                second = handoff.run(job, Path(tmp) / "cache")
            self.assertEqual(ask.call_count, 1)
            self.assertEqual(first[0], second[0])
            self.assertEqual((first[1], first[2]), (1.5, False))
            self.assertEqual((second[1], second[2]), (0.0, True))


if __name__ == "__main__":
    unittest.main()
