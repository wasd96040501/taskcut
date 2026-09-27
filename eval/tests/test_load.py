"""The context-load ledger, and the churn workload it is measured against."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from taskcut_eval import load, metrics, transcript, workload

REPO = Path(__file__).resolve().parents[2]
CWD = "/ws"


def call(n, tool, payload):
    return {"type": "assistant", "cwd": CWD, "message": {
        "id": f"m{n}", "usage": {"input_tokens": 1000 * n},
        "content": [{"type": "tool_use", "id": f"t{n}", "name": tool, "input": payload}],
    }}


def result(n, text):
    return {"type": "user", "cwd": CWD, "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": text}]}}


def reply(n):
    return {"type": "assistant", "cwd": CWD, "message": {"id": f"m{n}", "usage": {"input_tokens": 1000 * n}, "content": []}}


class Ledger(unittest.TestCase):
    def test_a_file_shown_then_edited_is_stale(self):
        points = load.series([
            call(1, "Read", {"file_path": "/ws/a.py"}), result(1, "x" * 400),
            call(2, "Edit", {"file_path": "a.py", "old_string": "x", "new_string": "y"}), result(2, "ok"),
            reply(3),
        ])
        self.assertEqual(points[1].stale, 0)
        # The read is a copy of the version before the edit; what the edit
        # sent is a copy of the version after it.
        self.assertEqual(points[2].stale, 100)
        self.assertEqual(points[2].conflicted, 1)
        self.assertEqual(points[2].busiest, "file:a.py")

    def test_the_same_file_read_twice_unchanged_is_redundant_not_stale(self):
        points = load.series([
            call(1, "Read", {"file_path": "/ws/a.py"}), result(1, "x" * 400),
            call(2, "Bash", {"command": "cat a.py"}), result(2, "x" * 400),
            reply(3),
        ])
        self.assertEqual((points[2].stale, points[2].redundant), (0, 100))

    def test_a_command_run_again_supersedes_its_earlier_output(self):
        points = load.series([
            call(1, "Bash", {"command": "cd /ws && pytest tests/test_a.py 2>&1 | tail -30"}), result(1, "F" * 800),
            call(2, "Bash", {"command": "pytest tests/test_a.py | tail -5"}), result(2, "." * 40),
            reply(3),
        ])
        self.assertEqual(points[2].stale, 200)

    def test_a_heredoc_that_writes_a_named_file_changes_it(self):
        changed, key = load.classify("Bash", {"command": "python3 - <<'EOF'\np = 'src/a.py'\ns = open(p).read()\nopen(p, 'w').write(s)\nEOF"}, CWD)
        self.assertEqual(changed, ["file:src/a.py"])
        self.assertTrue(key.startswith("cmd:"))

    def test_sed_in_place_changes_the_file_and_sed_n_shows_it(self):
        self.assertEqual(load.classify("Bash", {"command": "sed -i 's/a/b/' src/a.py"}, CWD)[0], ["file:src/a.py"])
        self.assertEqual(load.classify("Bash", {"command": "sed -n 1,40p /ws/src/a.py"}, CWD), ([], "file:src/a.py"))

    def test_a_compaction_empties_the_ledger(self):
        points = load.series([
            call(1, "Read", {"file_path": "/ws/a.py"}), result(1, "x" * 400),
            {"type": "system", "subtype": "compact_boundary"},
            reply(2),
        ])
        self.assertEqual((points[1].output, points[1].cuts), (0, 1))

    def test_a_subagent_is_not_the_main_context(self):
        side = dict(call(1, "Read", {"file_path": "/ws/a.py"}), isSidechain=True)
        self.assertEqual(load.series([side, reply(2)])[0].output, 0)


class Churn(unittest.TestCase):
    def generate(self, level):
        out = Path(tempfile.mkdtemp())
        subprocess.run(["python3", str(REPO / "eval/generators/churn.py"), str(out), level], check=True)
        return {p.name: p.read_text() for p in sorted(out.glob("*.py"))}

    def test_every_level_is_the_same_length_file_for_file(self):
        lo, hi = self.generate("lo"), self.generate("hi")
        self.assertEqual({k: len(v) for k, v in lo.items()}, {k: len(v) for k, v in hi.items()})
        self.assertNotEqual(lo, hi)

    def test_the_committed_workloads_are_what_the_generator_prints(self):
        for level in ("lo", "mid", "hi"):
            for flag, suffix in (([], ""), (["silent"], "-silent"), (["blind"], "-blind")):
                printed = subprocess.run(["python3", str(REPO / "eval/generators/churn.py"), "--workload", level, *flag],
                                         check=True, capture_output=True, text=True).stdout
                committed = (REPO / f"eval/workloads/churn-{level}{suffix}.json").read_text()
                self.assertEqual(json.loads(printed), json.loads(committed))
        for level in ("lo-dense", "hi-dense"):
            printed = subprocess.run(["python3", str(REPO / "eval/generators/churn.py"), "--workload", level, "blind"],
                                     check=True, capture_output=True, text=True).stdout
            committed = (REPO / f"eval/workloads/churn-{level}-blind.json").read_text()
            self.assertEqual(json.loads(printed), json.loads(committed))

    def test_the_dense_levels_are_the_same_length_too(self):
        lo, hi = self.generate("lo-dense"), self.generate("hi-dense")
        self.assertEqual({k: len(v) for k, v in lo.items()}, {k: len(v) for k, v in hi.items()})
        w = workload.load(REPO / "eval/workloads/churn-hi-dense-blind.json")
        root = workload.materialise(w, Path(tempfile.mkdtemp()) / "ws", REPO / "eval/generators")
        self.assertEqual(workload.check_ground_truth(w, root), [])

    def test_a_silent_probe_of_the_past_rejects_every_other_value_of_its_setting(self):
        w = workload.load(REPO / "eval/workloads/churn-hi-silent.json")
        root = workload.materialise(w, Path(tempfile.mkdtemp()) / "ws", REPO / "eval/generators")
        self.assertEqual(workload.check_ground_truth(w, root), [])
        past = [p for p in w.probes if p.id.startswith("H")]
        self.assertEqual(len(past), 6)
        self.assertTrue(all(p.reject and p.expect[0] not in p.reject for p in past))

    def test_every_tracked_value_is_in_the_material(self):
        w = workload.load(REPO / "eval/workloads/churn-hi.json")
        root = workload.materialise(w, Path(tempfile.mkdtemp()) / "ws", REPO / "eval/generators")
        self.assertEqual(workload.check_ground_truth(w, root), [])

    def test_a_step_is_graded_current_stale_or_other(self):
        w = workload.load(REPO / "eval/workloads/churn-hi.json")
        step = w.tracked.steps[1]
        key, value = next((k, v) for k, v in step.items() if v["stale"])
        others = [k for k in step if k != key]
        answer = f"IN FORCE: {key}={value['stale'][0]} {others[0]}={step[others[0]]['current']} {others[1]}=1"
        t = transcript.Transcript(path=None, turns=[transcript.Turn(prompt=w.steps()[1], texts=[answer], tools=["Bash"])])
        graded = metrics.tracking(t, w)
        self.assertEqual(graded.per_step[1][key], metrics.STALE)
        self.assertEqual(graded.per_step[1][others[0]], metrics.CURRENT)
        self.assertEqual(graded.per_step[1][others[1]], metrics.OTHER)
        self.assertEqual(graded.per_step[1][others[2]], metrics.MISSING)
        self.assertEqual(graded.calls[:2], (0, 1))


if __name__ == "__main__":
    unittest.main()
