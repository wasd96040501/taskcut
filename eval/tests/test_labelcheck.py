"""Checking the handoff labels: the sample, the relabelling calls, and agreement."""

import unittest
from collections import Counter

from taskcut_eval import labelcheck


class Sample(unittest.TestCase):
    def test_no_session_gives_more_than_its_cap(self):
        rows = [{"session": "big", "segment": 0, "step": n, "label": "KEEP"} for n in range(50)] + \
               [{"session": s, "segment": 0, "step": 0, "label": "COMPACT"} for s in "abcdef"]
        chosen = labelcheck.sample(rows, per_label=10, cap=3)
        self.assertEqual(Counter(r["label"] for r in chosen), {"KEEP": 3, "COMPACT": 6})


class Agreement(unittest.TestCase):
    def test_agreement_and_kappa_over_shared_keys(self):
        a = {1: "K", 2: "C", 3: "C", 4: "C", 5: "K"}
        b = {1: "K", 2: "C", 3: "K", 4: "C", 6: "C"}
        n, agree, kappa, pairs = labelcheck.agreement(a, b)
        self.assertEqual((n, agree), (4, 0.75))
        self.assertAlmostEqual(kappa, 0.5)
        self.assertEqual(pairs[("C", "K")], 1)

    def test_perfect_agreement_on_one_value_has_no_kappa(self):
        n, agree, kappa, _ = labelcheck.agreement({1: "C"}, {1: "C"})
        self.assertEqual((n, agree), (1, 1.0))
        self.assertNotEqual(kappa, kappa)


if __name__ == "__main__":
    unittest.main()
