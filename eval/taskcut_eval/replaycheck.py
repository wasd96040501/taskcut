"""Whether the replay gives the judge what a live session gives it.

The replay rebuilds `$.session.messages()` from a transcript. If that differs
from what the engine hands a hook -- a message kind the transcript writes and
the engine leaves out, text joined another way, a compaction cut elsewhere --
then every number the replay reports is about a prompt the judge never sees.
So this runs one real session with taskcut and a recorder plugin side by side
(eval/replaycheck): at every step of the main loop the recorder writes the
judge's prompt as taskcut would build it there, from what the engine holds.
Afterwards the transcript is replayed, the same prompts are built from it
under node with the same judge.ts, and the two are compared, step by step.

The session is the mechanism check's workspace with one long turn of four
pieces -- kept on a task list, so the list's calls are in it -- compacted
by taskcut between pieces and carried on with `Continue.`, and a question
turn after it. That puts in it every kind of message the judge reads
differently: a request, tool calls and results, a task list, a compaction's
summary, a plugin's prompt.

A few minutes and well under a dollar; it needs a terminal and credentials,
so it is not in CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import driver, mechanism, replay

#: The recorder, with the judge it records copied in beside it.
HARNESS = Path(__file__).resolve().parent.parent / "replaycheck"

STEPS = [
    "Run `wc -l a.txt` and tell me the number.",
    "Keep a task list for this. " + mechanism._long_turn(1),
    "Without running any tool: list every task I have given you in this conversation, with its result.",
]

#: The task-list tools are off in a session unless this is set (2.1.280).
ENV = {"CLAUDE_CODE_ENABLE_TODO_TOOLS": "1"}

NODE_PROMPTS = """
import { readFileSync } from 'node:fs'
const { judgePrompt } = await import(process.argv[1])
const cases = JSON.parse(readFileSync(0, 'utf8'))
process.stdout.write(JSON.stringify(cases.map((c) => judgePrompt(c.messages, c.step))))
"""


def prompts(judge: Path, cases: list[dict]) -> list[str]:
    """judgePrompt from `judge` over each case, `{messages, step}`, under node."""
    out = subprocess.run(["node", "--input-type=module", "-e", NODE_PROMPTS, str(judge)],
                         input=json.dumps(cases), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def prepare(judge: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(HARNESS, destination)
    shutil.copy(judge, destination / "hooks" / "judge.ts")
    return destination


def drive(workspace: Path, plugins: list[Path], model: str, log=print, debug_file: Path | None = None) -> None:
    env = {**ENV, **mechanism.ARM.env}
    session = driver.Session(workspace, plugins, env, model, debug_file=debug_file)
    try:
        session.read_until_quiet(quiet=3.0, timeout=120)
        session.accept_trust_prompt()
        for index, step in enumerate(STEPS, 1):
            log(f"  step {index}/{len(STEPS)} settled={session.ask(step)}")
    finally:
        session.close()


@dataclass
class Outcome:
    steps: int
    matched: int
    mismatches: list[str]
    kinds: dict

    @property
    def passed(self) -> bool:
        return self.steps > 0 and not self.mismatches


def _first_difference(a: str, b: str) -> str:
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"at character {i}: live {a[max(0, i - 60):i + 80]!r} / replay {b[max(0, i - 60):i + 80]!r}"


def compare(records: list[dict], rebuilt: dict, judge: Path) -> Outcome:
    """The recorded prompts against the replay's, step by step. A record with
    no response in it -- a step taskcut ended before it was sent -- is not a
    step of the transcript, and is left out."""
    live = [r for r in records if r["stopReason"] is not None or r["step"]["text"] or r["step"]["calls"]]
    steps = rebuilt["steps"]
    mismatches = []
    if len(live) != len(steps):
        mismatches.append(f"{len(live)} steps recorded live, {len(steps)} in the transcript")
    cases = [{"messages": rebuilt["segments"][s["segment"]][: s["pos"]], "step": s["step"]} for s in steps]
    rebuilt_prompts = prompts(judge, cases)
    matched = 0
    for record, s, prompt in zip(live, steps, rebuilt_prompts):
        if record["step"]["text"].strip() != s["step"]["text"].strip() or [c["name"] for c in record["step"]["calls"]] != [c["name"] for c in s["step"]["calls"]]:
            mismatches.append(f"step {s['n']}: a different step live ({record['step']['text'][:60]!r}) than in the transcript ({s['step']['text'][:60]!r})")
            continue
        if record["prompt"] != prompt:
            mismatches.append(f"step {s['n']}: prompts differ {_first_difference(record['prompt'], prompt)}")
            continue
        matched += 1
    kinds = {
        "segments": len(rebuilt["segments"]),
        "requests": sum(m["role"] == "user" and not m.get("toolResults") for seg in rebuilt["segments"] for m in seg),
        "task-list calls": sum(c["name"] in ("TaskCreate", "TaskUpdate", "TodoWrite") for s in steps for c in s["step"]["calls"]),
        "judged": len(replay.judged(rebuilt)),
    }
    return Outcome(steps=len(steps), matched=matched, mismatches=mismatches, kinds=kinds)
