"""An end-to-end check of the mechanism itself, in a real session.

The benchmark measures what taskcut does to real work at a realistic floor,
where a session crosses it once if at all. This drives one short session with
the floor set low enough to cross it twice, and asserts, from the transcript,
the things that have to hold every time:

* below the floor nothing happens -- no judgement, no tool, no reminder;
* inside one long turn, a piece finished with another to follow is compacted
  there and then, and the work picks back up;
* the last piece is not compacted, and neither is the end of any turn;
* what was compacted can still be recalled;
* crossing again, in a second long turn, compacts again;
* the work that was interrupted gets finished.

It costs a few minutes and around a dollar, and needs a terminal
and credentials, so it is not in CI.
"""

from __future__ import annotations

import json
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import driver
from .arms import Arm
from .transcript import CONTINUE_OPENING

#: Low enough that a short session crosses it twice. The judge, the cut and
#: the ledger do not know what the floor is, only whether it has been passed.
FLOOR = 5

ARM = Arm(name="mechanism", description="", env={"TASKCUT": "1"}, config={"floorPercent": FLOOR})

#: A file of about fifteen thousand tokens, so that reading two of them moves a
#: million-token window across five percent.
_LINES = 700

#: What each file ends with, so that what was read can be checked exactly.
LAST_LINES = {
    "notes1.txt": "PELICAN-93",
    "notes2.txt": "KESTREL-41",
    "notes3.txt": "MARLIN-07",
    "notes4.txt": "OSPREY-12",
    "notes5.txt": "HERON-58",
    "notes6.txt": "EGRET-30",
}


def _long_turn(first: int) -> str:
    """One message, four pieces, nobody stepping in: three files to read, each
    about fifteen thousand tokens, and a last piece that reads none."""
    files = [first, first + 1, first + 2]
    return (
        "Work through these tasks in order, one at a time, without stopping to ask me anything. "
        "Finish and check each one before you start the next. "
        + " ".join(f"{k}. Read notes{n}.txt in full, write its last line to answer{n}.txt, and check the file with cat."
                   for k, n in enumerate(files, 1))
        + f" 4. Run `wc -l a.txt` and write the number to count{first}.txt. "
        "When all four are done, list each task with its result and end with the words ALL DONE."
    )


STEPS = [
    "Run `wc -l a.txt` and tell me the number.",
    _long_turn(1),
    "Without running any tool: list every task I have given you in this conversation, with its result.",
    _long_turn(4),
]

#: The long turns, and what the files each writes must hold once it is over.
LONG_TURNS = {
    STEPS[1]: {"answer1.txt": "PELICAN-93", "answer2.txt": "KESTREL-41", "answer3.txt": "MARLIN-07", "count1.txt": "3"},
    STEPS[3]: {"answer4.txt": "OSPREY-12", "answer5.txt": "HERON-58", "answer6.txt": "EGRET-30", "count4.txt": "3"},
}


def _filler(rng: random.Random, count: int) -> list[str]:
    words = "lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt".split()
    return [" ".join(rng.choice(words) for _ in range(12)) for _ in range(count)]


def materialise(root: Path) -> Path:
    """A fresh workspace with the files the steps read."""
    if root.exists():
        subprocess.run(["rm", "-rf", str(root)], check=True)
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.txt").write_text("alpha\nbeta\ngamma\n")
    (root / "b.txt").write_text("delta\nepsilon\n")
    rng = random.Random(7)
    for name, last in LAST_LINES.items():
        (root / name).write_text("\n".join([*_filler(rng, _LINES), last]) + "\n")
    return root


def drive(workspace: Path, plugin: Path, arm: Arm, model: str, log=print) -> None:
    session = driver.Session(workspace, plugin, dict(arm.env), model)
    try:
        session.read_until_quiet(quiet=3.0, timeout=120)
        session.accept_trust_prompt()
        for index, step in enumerate(STEPS, 1):
            log(f"  step {index}/{len(STEPS)} settled={session.ask(step)}")
    finally:
        session.close()


@dataclass
class Turn:
    """One prompt and what happened until the next, as the mechanism sees it."""

    prompt: str
    #: Input tokens of each request, in order: what the model was carrying.
    contexts: list[int] = field(default_factory=list)
    #: taskcut's own notices: the notice of a cut.
    verdicts: list[str] = field(default_factory=list)
    #: The input of every call the turn made, as JSON, in order.
    touched: list[str] = field(default_factory=list)
    #: Tokens before each cut the turn ended with.
    cuts: list[int] = field(default_factory=list)
    #: For each cut, where in `touched` the calls of the step it was judged on
    #: begin: the last step before it.
    cut_steps: list[int] = field(default_factory=list)
    #: Where in `touched` the calls of the latest step begin.
    step_start: int = 0
    request: str | None = None
    closes: list[dict] = field(default_factory=list)
    searches: int = 0
    reminders: int = 0
    texts: list[str] = field(default_factory=list)

    @property
    def carried(self) -> int:
        """What the turn ended with: the input of its last request."""
        return self.contexts[-1] if self.contexts else 0

    @property
    def active(self) -> bool:
        return bool(self.verdicts or self.cuts or self.closes or self.searches or self.reminders)


def _is_prompt(record: dict) -> str | None:
    if record.get("isCompactSummary"):
        return None
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    blocks = [b for b in content or [] if isinstance(b, dict)]
    if blocks and not any(b.get("type") == "tool_result" for b in blocks):
        return " ".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    return None


def turns(path: Path) -> list[Turn]:
    """The transcript as turns. A prompt a cut re-emitted opens a turn with
    nothing in it, which is what it is."""
    out: list[Turn] = []
    seen: set[str] = set()
    for line in path.read_text(errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        kind, message = record.get("type"), record.get("message") or {}
        if kind == "user":
            prompt = _is_prompt(record)
            if prompt is not None:
                out.append(Turn(prompt=prompt))
            elif out and REMINDER_WORDS in json.dumps(message.get("content")):
                out[-1].reminders += 1
            continue
        if not out:
            continue
        turn = out[-1]
        if kind == "attachment" and REMINDER_WORDS in json.dumps(record.get("attachment")):
            # A hook's context rides beside a tool result as an attachment.
            turn.reminders += 1
        elif kind == "system" and record.get("subtype") == "compact_boundary":
            turn.cuts.append(int((record.get("compactMetadata") or {}).get("preTokens") or 0))
            turn.cut_steps.append(turn.step_start)
        elif kind == "system" and str(record.get("content") or "").startswith("taskcut:"):
            turn.verdicts.append(str(record.get("content")))
        elif kind == "assistant":
            usage, request = message.get("usage") or {}, record.get("requestId") or message.get("id")
            if request != turn.request:
                # One step's response can span several records; a new request is a new step.
                turn.request, turn.step_start = request, len(turn.touched)
            if usage and request not in seen:
                seen.add(request)
                turn.contexts.append(
                    usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("input_tokens", 0)
                )
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") == "mcp__taskcut__close_task":
                    turn.closes.append(dict(block.get("input") or {}))
                elif block.get("type") == "tool_use" and block.get("name") == "ToolSearch":
                    turn.searches += 1
                if block.get("type") == "tool_use":
                    turn.touched.append(json.dumps(block.get("input")))
                elif block.get("type") == "text" and str(block.get("text")).strip():
                    turn.texts.append(str(block.get("text")))
    return out


#: Words from the reminder 0.5.0 attached for close_task: a guard that nothing
#: like it comes back.
REMINDER_WORDS = "context window is filling up"


@dataclass
class Result:
    name: str
    passed: bool
    detail: str


def check(path: Path, window: int, workspace: Path | None = None) -> list[Result]:
    """Every property the mechanism promises, asserted against one transcript
    and, for the long turns, the files they left in the workspace."""
    everything = turns(path)
    work = [t for t in everything if t.contexts]  # turns that ran, not ones ended before a request
    floor = window * FLOOR / 100
    # A whole percentage, compared as the plugin compares it: allow a point of
    # rounding either side rather than assert on the boundary itself.
    point = window / 100
    below = [t for t in work if t.carried < floor - point]
    cuts = [c for t in everything for c in t.cuts]
    # Every compaction taskcut makes ends a turn it then carries on: one the
    # next turn does not carry on was made at the end of a turn.
    at_the_end = [
        t for k, t in enumerate(everything)
        if t.cuts and not (k + 1 < len(everything) and everything[k + 1].prompt.startswith(CONTINUE_OPENING))
    ]

    def long_turn(message: str) -> list[Turn]:
        """The turn that message opened, and every turn taskcut started to carry it on."""
        start = next((k for k, t in enumerate(everything) if t.prompt.strip() == message), None)
        if start is None:
            return []
        parts = [everything[start]]
        for t in everything[start + 1:]:
            if not t.prompt.startswith(CONTINUE_OPENING):
                break
            parts.append(t)
        return [t for t in parts if t.contexts]

    inside: dict[str, int] = {}
    after_last: dict[str, int | None] = {}
    finished: dict[str, bool] = {}
    for n, (message, answers) in enumerate(LONG_TURNS.items(), 1):
        ran = long_turn(message)
        count = next(name for name in answers if name.startswith("count"))
        last = next((k for k, t in enumerate(ran) if any(count in call for call in t.touched)), None)
        inside[f"turn {n}"] = sum(len(t.cuts) for t in ran[:-1])
        if last is None:
            after_last[f"turn {n}"] = None
        else:
            # A cut judged on the step that starts the last piece is the move to
            # it, even when that step does the whole piece; one judged on any
            # step after that is a cut after the last piece.
            call = next(k for k, c in enumerate(ran[last].touched) if count in c)
            after_last[f"turn {n}"] = sum(start > call for start in ran[last].cut_steps) + sum(len(t.cuts) for t in ran[last + 1:])
        written = {
            name: (workspace / name).read_text().strip() if workspace and (workspace / name).exists() else None
            for name in answers
        }
        ending = " ".join(ran[-1].texts) if ran else ""
        finished[f"turn {n}"] = all(written[name] == want for name, want in answers.items()) and "ALL DONE" in ending

    recalled = next((t for t in work if t.prompt.strip() == STEPS[2]), None)
    recall = " ".join(recalled.texts) if recalled else ""
    wanted = ["3", *(LAST_LINES[f"notes{n}.txt"] for n in (1, 2, 3))]
    skipped = [v for t in everything for v in t.verdicts if "skipped" in v]
    closes = [c for t in work for c in t.closes]
    return [
        Result(
            "quiet below the floor",
            not any(t.active for t in below),
            f"{len(below)} turn(s) below the floor, {sum(t.active for t in below)} with any taskcut activity",
        ),
        Result(
            "a piece finished inside a turn, with another to follow, is compacted there",
            all(inside.values()) and not skipped,
            f"compactions inside each long turn: {inside}; {len(skipped)} skipped",
        ),
        Result(
            "the last piece is not compacted",
            all(v == 0 for v in after_last.values()),
            f"compactions from the last piece on: {after_last}",
        ),
        Result(
            "nothing is compacted at the end of a turn",
            not at_the_end,
            f"{len(at_the_end)} turn(s) ended in a compaction nobody carried on",
        ),
        Result(
            "nothing is compacted below the floor",
            all(c >= floor - point for c in cuts),
            f"compactions at {cuts}",
        ),
        Result("crossing again compacts again", len(cuts) >= 2, f"{len(cuts)} compaction(s)"),
        Result(
            "what was compacted can be recalled",
            all(w in recall for w in wanted),
            "missing: " + ", ".join(w for w in wanted if w not in recall) if any(w not in recall for w in wanted) else "all four",
        ),
        Result(
            "the work that was interrupted gets finished",
            all(finished.values()),
            f"files right and ALL DONE: {finished}",
        ),
        Result(
            "the working model is never asked for anything",
            not closes and not any(t.searches or t.reminders for t in work),
            f"{len(closes)} close_task, {sum(t.searches for t in work)} ToolSearch, "
            f"{sum(t.reminders for t in work)} reminder(s)",
        ),
    ]
