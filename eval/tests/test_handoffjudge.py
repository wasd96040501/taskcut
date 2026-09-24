"""Scoring the judge against handoff labels: which steps are asked, that a
verdict held is not asked for again, and where a segment's first compaction
lands."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskcut_eval import handoffjudge
from taskcut_eval.handoffjudge import Step


def step(session, segment, n, label):
    return Step(session, segment, n, label, 400_000, {"id": f"{session}#{n}"})


STEPS = [step("a", 0, n, label) for n, label in [(1, "KEEP"), (2, "COMPACT"), (3, "COMPACT"), (4, "COMPACT")]] + \
        [step("b", 0, n, "COMPACT") for n in range(1, 11)]


def answers(verdicts: dict[str, list[str]]) -> dict:
    return {(i, r): {"id": i, "run": r, "verdict": v, "usage": None} for i, vs in verdicts.items() for r, v in enumerate(vs)}


class Select(unittest.TestCase):
    def test_every_keep_a_sample_of_compact_and_each_segments_head(self):
        chosen = {s.id for s in handoffjudge.select(STEPS, sample=0, head=2)}
        self.assertEqual(chosen, {"a#1", "a#2", "b#1", "b#2"})
        self.assertEqual(len(handoffjudge.select(STEPS, sample=5, head=0)), 6)


class Ask(unittest.TestCase):
    def test_a_verdict_held_is_not_asked_for_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "v.jsonl"
            reply = lambda cases, *a, **k: [{"id": c["id"], "run": r, "verdict": "KEEP", "text": ""} for c in cases for r in range(a[3])]
            with mock.patch.object(handoffjudge.judgebench, "ask", side_effect=reply) as ask:
                handoffjudge.ask(STEPS[:2], [], Path(tmp), Path(tmp), store, "sonnet", 2, 1, log=lambda _: None)
                handoffjudge.ask(STEPS[:3], [], Path(tmp), Path(tmp), store, "sonnet", 2, 1, log=lambda _: None)
            self.assertEqual([len(c.args[0]) for c in ask.call_args_list], [2, 1])
            self.assertEqual(len(handoffjudge.cached(store)), 6)


class Score(unittest.TestCase):
    def test_the_first_compaction_lands_where_the_judge_first_says_so(self):
        given = {s.id: ["KEEP"] for s in STEPS}
        given["a#1"] = ["COMPACT"]
        given["b#3"] = ["COMPACT"]
        text = "\n".join(handoffjudge.score(STEPS, answers(given), "sonnet", 1, head=4))
        self.assertIn("on KEEP", text)
        self.assertIn("on COMPACT", text)
        self.assertIn("compacted a KEEP step 1/1: a#1", text)
        self.assertIn("compacts on KEEP     100.0%", text)


if __name__ == "__main__":
    unittest.main()
