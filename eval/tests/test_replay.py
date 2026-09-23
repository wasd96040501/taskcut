"""The replay: that it rebuilds what the judge would have been given, and that
its scores mean what they say -- tested against judges whose answers are known."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from taskcut_eval import replay, replaycheck

REPO = Path(__file__).resolve().parents[2]
JUDGE = REPO / "hooks" / "judge.ts"
HAS_NODE = shutil.which("node") is not None


def user(text, **extra):
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def result(tool_use_id):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": "OUTPUT"}]}}


def said(mid, text=None, call=None, stop=None, context=100):
    """One record of a response: Claude Code writes one per content block."""
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if call is not None:
        content.append({"type": "tool_use", "id": f"t-{mid}-{call[0]}", "name": call[0], "input": call[1]})
    return {"type": "assistant", "message": {"id": mid, "role": "assistant", "content": content, "stop_reason": stop,
                                             "usage": {"input_tokens": 1, "cache_read_input_tokens": context - 1}}}


#: Two pieces in one turn, a compaction taskcut made after the first, and the
#: turn it carried on with. What each step's judged-ness should be is in the
#: comment beside it.
SESSION = [
    user("Fix issue 1, then issue 2."),
    said("m0", call=("Bash", {"command": "pytest", "description": "Run the tests"}), stop="tool_use"),  # first of a turn: no
    result("t-m0-Bash"),
    said("m1", text="Issue 1 fails in parse(). Fixing it."),  # one response, two records
    said("m1", call=("Edit", {"file_path": "/home/me/p.py"}), stop="tool_use"),  # judged
    result("t-m1-Edit"),
    said("m2", text="Issue 1 done. Issue 2:", call=("Read", {"file_path": "/home/me/q.py"}), stop="tool_use"),  # judged
    result("t-m2-Read"),
    {"type": "system", "subtype": "compact_boundary"},
    user("This session is being continued from a previous conversation. Summary: issue 1 done.", isCompactSummary=True),
    user("The taskcut plugin sent a message: Continue."),
    user("<system-reminder>not typed</system-reminder>", isMeta=True),
    said("m3", call=("Read", {"file_path": "/home/me/q.py"}), stop="tool_use"),  # first of a turn: no
    result("t-m3-Read"),
    said("m4", text="Reading on.", call=("Grep", {"pattern": "x"}), stop="tool_use"),  # nothing changed since the compaction: no
    result("t-m4-Grep"),
    said("m5", text="Fixing issue 2.", call=("Edit", {"file_path": "/home/me/q.py"}), stop="tool_use"),  # still none before it: no
    result("t-m5-Edit"),
    said("m6", text="Issue 2 done.", call=("Bash", {"command": "pytest"}), stop="tool_use"),  # judged
    result("t-m6-Bash"),
    said("m7", text="", call=("Bash", {"command": "git diff"}), stop="tool_use"),  # says nothing: no
    result("t-m7-Bash"),
    said("m8", text="Both issues are done.", stop="end_turn"),  # ends the turn: no
    {"type": "assistant", "isSidechain": True, "message": {"id": "sub", "content": [{"type": "text", "text": "a sub-agent"}], "stop_reason": "end_turn"}},
]


class Parse(unittest.TestCase):
    def setUp(self):
        self.replay = replay.parse(SESSION)

    def test_one_step_per_response_whatever_the_records(self):
        self.assertEqual(len(self.replay["steps"]), 9)
        m1 = self.replay["steps"][1]
        self.assertEqual(m1["step"], {"text": "Issue 1 fails in parse(). Fixing it.", "calls": [{"name": "Edit", "input": {"file_path": "/home/me/p.py"}}]})
        self.assertEqual(m1["stop_reason"], "tool_use")

    def test_the_engine_holds_a_response_a_record_at_a_time(self):
        held = self.replay["segments"][0]
        m1 = self.replay["steps"][1]
        self.assertEqual(held[m1["pos"]], {"role": "assistant", "text": "Issue 1 fails in parse(). Fixing it.", "toolUses": []})
        self.assertEqual([u["tool"] for u in held[m1["pos"] + 1]["toolUses"]], ["Edit"])
        self.assertEqual(held[m1["pos"] + 2]["toolResults"][0]["tool_use_id"], "t-m1-Edit")

    def test_a_compaction_starts_a_new_segment(self):
        self.assertEqual(len(self.replay["segments"]), 2)
        self.assertEqual([s["segment"] for s in self.replay["steps"]], [0, 0, 0, 1, 1, 1, 1, 1, 1])

    def test_messages_before_a_step_are_what_the_engine_held(self):
        s = self.replay["steps"][3]
        before = self.replay["segments"][1][: s["pos"]]
        self.assertEqual([m["role"] for m in before], ["user", "user"])
        self.assertTrue(before[0]["text"].startswith("This session is being continued"))
        self.assertTrue(before[1]["text"].startswith("The taskcut plugin sent a message"))

    def test_tool_results_carry_no_output(self):
        results = [m for seg in self.replay["segments"] for m in seg if m.get("toolResults")]
        self.assertTrue(results)
        self.assertTrue(all(r["text"] == "" for m in results for r in m["toolResults"]))

    def test_turns_and_their_step_indexes(self):
        self.assertEqual([(s["turn"], s["index"]) for s in self.replay["steps"]],
                         [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (1, 5)])

    def test_context_is_the_request_whole(self):
        self.assertEqual(self.replay["steps"][0]["context"], 100)

    def test_judged_follows_register_ts(self):
        self.assertEqual(replay.judged(self.replay), [1, 2, 6])


class Preserved(unittest.TestCase):
    """A compaction keeps the latest messages whole, after its summary, and
    the engine holds them there: so must the replay."""

    def test_the_preserved_messages_follow_the_summary(self):
        session = [
            {**user("Do A then B."), "uuid": "u1"},
            {**said("m0", text="A is done. Now B.", stop=None), "uuid": "a1"},
            {**said("m0", call=("Bash", {"command": "b"}), stop="tool_use"), "uuid": "a2"},
            {**result("t-m0-Bash"), "uuid": "r1"},
            {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"preservedMessages": {"uuids": ["a1", "a2", "r1", "gone"]}}},
            user("This session is being continued from a previous conversation. Summary.", isCompactSummary=True),
            user("The taskcut plugin sent a message: Continue."),
            said("m1", text="B next.", call=("Bash", {"command": "c"}), stop="tool_use"),
        ]
        rebuilt = replay.parse(session)
        segment = rebuilt["segments"][1]
        self.assertEqual([(m["role"], m["text"][:12], [u["tool"] for u in m["toolUses"]], len(m.get("toolResults", []))) for m in segment], [
            ("user", "This session", [], 0),
            ("assistant", "A is done. N", [], 0),
            ("assistant", "", ["Bash"], 0),
            ("user", "", [], 1),
            ("user", "The taskcut ", [], 0),
            ("assistant", "B next.", ["Bash"], 0),
        ])
        self.assertEqual(rebuilt["steps"][1]["pos"], 5)


class Scrub(unittest.TestCase):
    def test_home_as_a_path_and_as_a_directory_name(self):
        value = {"a": ["/Users/me/x", "~/.claude/projects/-Users-me--cache-x/y", 3]}
        self.assertEqual(replay.scrub(value, "/Users/me"), {"a": ["~/x", "~/.claude/projects/-~--cache-x/y", 3]})


@unittest.skipUnless(HAS_NODE, "node reads hooks/judge.ts")
class AgreesWithThePlugin(unittest.TestCase):
    def test_read_only_tools_are_the_judges(self):
        script = "import { READ_ONLY_TOOLS } from './hooks/judge.ts'; console.log(JSON.stringify([...READ_ONLY_TOOLS]))"
        out = subprocess.run(["node", "--input-type=module", "-e", script], cwd=REPO, capture_output=True, text=True, check=True).stdout
        self.assertEqual(set(json.loads(out)), set(replay.READ_ONLY_TOOLS))


class Labels(unittest.TestCase):
    def setUp(self):
        self.replay = {"name": "s", **replay.parse(SESSION)}
        self.replay["judged"] = replay.judged(self.replay)

    def test_a_template_reads_back(self):
        text = replay.labels_template(self.replay, "s: a session\nsecond line", {1: "S", 2: "N"})
        self.assertEqual(replay.read_labels(text), {1: "S", 2: "N", 6: "?"})
        self.assertTrue(text.startswith("# s: a session\n# second line\n"))

    def test_every_judged_step_must_be_labelled_and_nothing_else(self):
        self.assertEqual(replay.check_labels(self.replay, {1: "S", 2: "N", 6: "S"}), [])
        problems = replay.check_labels(self.replay, {1: "S", 5: "S", 6: "?"})  # 2 missing, 5 extra, 6 unsure
        self.assertEqual(len(problems), 3, problems)

    def test_a_line_that_is_not_a_label_is_refused(self):
        with self.assertRaises(ValueError):
            replay.read_labels("12 X  what")
        with self.assertRaises(ValueError):
            replay.read_labels("12 N\n12 S")

    def test_a_window_is_an_n_and_the_es_just_before_it(self):
        self.assertEqual(replay.windows({1: "S", 2: "E", 3: "E", 4: "N", 5: "E", 6: "S", 7: "N"}), [[2, 3, 4], [7]])


def verdicts(nexts: dict[str, list[bool]]):
    return {k: [replay.Verdict(next=v, answered=True, cost=0.001, tokens_in=10, tokens_out=2, ms=5) for v in vs] for k, vs in nexts.items()}


class Scoring(unittest.TestCase):
    """Judges whose answers are known: the scores have to come out as they must."""

    LABELS = {"s": {1: "S", 2: "E", 3: "N", 4: "S", 5: "N", 6: "S"}}
    SETS = {"s": {"steps": [{"n": n, "step": {"text": t}, "context": 0} for n, t in
                            [(1, "reading"), (2, "checkpoint"), (3, "issue 1 done; issue 2"), (4, "tests pass, tidying"), (5, "done; next"), (6, "editing")]],
                  "judged": [1, 2, 3, 4, 5, 6]}}

    def judge(self, rule, repeats=3):
        return verdicts({f"s#{n}": [rule(n, r) for r in range(repeats)] for n in self.LABELS["s"]})

    def test_an_oracle_catches_everything_and_calls_nothing_wrong(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: self.LABELS["s"][n] == "N"))
        self.assertEqual((s.boundaries, s.false_next, s.hard_same, s.agreement), (1.0, 0.0, 1.0, 1.0))

    def test_always_same_catches_nothing(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: False))
        self.assertEqual((s.boundaries, s.false_next), (0.0, 0.0))

    def test_always_next_catches_everything_and_is_wrong_everywhere_else(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: True))
        self.assertEqual((s.boundaries, s.false_next, s.hard_same), (1.0, 1.0, 0.0))

    def test_next_at_the_e_before_the_boundary_catches_it(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: n in (2, 5)))
        self.assertEqual((s.boundaries, s.false_next), (1.0, 0.0))

    def test_an_e_step_counts_against_nothing(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: n == 2))
        self.assertEqual(s.false_next, 0.0)

    def test_a_judge_that_flips_between_repeats_is_counted_per_repeat(self):
        s = replay.score(self.SETS, self.LABELS, self.judge(lambda n, r: self.LABELS["s"][n] == "N" and r == 0))
        self.assertAlmostEqual(s.boundaries, 1 / 3)
        self.assertLess(s.agreement, 1.0)

    def test_an_unanswered_call_is_same(self):
        answers = [{"id": "s#3", "run": 0, "verdict": "unanswered: api-error 429 rate_limit", "usage": None}]
        v = replay.verdicts(answers, "sonnet")["s#3"][0]
        self.assertEqual((v.next, v.answered, v.cost), (False, False, 0.0))

    def test_cost_is_list_price(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000, "cache_creation_input_tokens": 0}
        self.assertAlmostEqual(replay.price("sonnet", usage), 2.0 + 1.0 + 0.2)
        self.assertAlmostEqual(replay.price("claude-haiku-4-5", usage), 1.0 + 0.5 + 0.1)
        with self.assertRaises(KeyError):
            replay.price("gpt", usage)


class Intervals(unittest.TestCase):
    def test_the_interval_holds_the_rate(self):
        units = [[True, True, False]] * 10 + [[False] * 3] * 10
        lo, hi = replay.interval(units)
        self.assertLessEqual(lo, 1 / 3)
        self.assertGreaterEqual(hi, 1 / 3)
        self.assertLess(lo, hi)

    def test_the_same_judge_twice_differs_by_nothing(self):
        units = [[True, False, True], [False, False, False], [True, True, True]]
        self.assertEqual(replay.paired(units, units), (0.0, 0.0, 0.0))

    def test_a_judge_that_misses_every_boundary_is_worse_beyond_doubt(self):
        a = [[True] * 3 for _ in range(30)]
        b = [[False] * 3 for _ in range(30)]
        d, lo, hi = replay.paired(a, b)
        self.assertEqual((d, lo, hi), (-1.0, -1.0, -1.0))


class CommittedSets(unittest.TestCase):
    """The sets in eval/replay, as committed."""

    def test_their_labels_cover_exactly_the_steps_taskcut_judges(self):
        sets, labels, _ = replay.load_sets([REPO / "eval" / "replay"])
        self.assertTrue(sets)
        for name, s in sets.items():
            self.assertEqual(s["judged"], replay.judged(s), name)

    def test_they_hold_no_home_directory(self):
        for path in (REPO / "eval" / "replay").glob("*.json"):
            text = path.read_text()
            self.assertNotIn(str(Path.home()), text, path.name)
            self.assertNotIn(str(Path.home()).replace("/", "-"), text, path.name)


@unittest.skipUnless(HAS_NODE, "node builds the prompts with hooks/judge.ts")
class TheCheckCatchesADifference(unittest.TestCase):
    """replaycheck.compare, fed records it must accept and records it must not."""

    def setUp(self):
        self.rebuilt = replay.parse(SESSION)
        cases = [{"messages": self.rebuilt["segments"][s["segment"]][: s["pos"]], "step": s["step"]} for s in self.rebuilt["steps"]]
        prompts = replaycheck.prompts(JUDGE, cases)
        self.records = [{"turnId": "t", "index": s["index"], "stopReason": s["stop_reason"], "step": s["step"], "prompt": p, "messages": 0}
                        for s, p in zip(self.rebuilt["steps"], prompts)]

    def test_the_same_prompts_pass(self):
        outcome = replaycheck.compare(self.records, self.rebuilt, JUDGE)
        self.assertTrue(outcome.passed, outcome.mismatches)
        self.assertEqual(outcome.matched, 9)

    def test_a_prompt_that_differs_is_named(self):
        self.records[6]["prompt"] = self.records[6]["prompt"].replace("Issue 2 done", "Issue 2 finished")
        outcome = replaycheck.compare(self.records, self.rebuilt, JUDGE)
        self.assertFalse(outcome.passed)
        self.assertEqual(len(outcome.mismatches), 1)
        self.assertIn("step 6", outcome.mismatches[0])

    def test_a_step_the_engine_had_and_the_transcript_did_not_is_named(self):
        outcome = replaycheck.compare(self.records[:-1], self.rebuilt, JUDGE)
        self.assertFalse(outcome.passed)

    def test_a_step_taskcut_ended_before_it_was_sent_is_not_one(self):
        pseudo = {"turnId": "t", "index": 3, "stopReason": None, "step": {"text": "", "calls": []}, "prompt": "", "messages": 0}
        outcome = replaycheck.compare(self.records[:3] + [pseudo] + self.records[3:], self.rebuilt, JUDGE)
        self.assertTrue(outcome.passed, outcome.mismatches)
