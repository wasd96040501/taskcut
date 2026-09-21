"""An end-to-end check of the mechanism itself, in a real session.

The benchmark measures what taskcut does to real work at a realistic floor,
where a session crosses it once if at all. This drives one short session with
the floor set low enough to cross it twice, and asserts, from the transcript,
the things that have to hold every time:

* below the floor nothing happens -- no judgement, no tool, no reminder;
* past it, a turn that ends in a question is judged unfinished and kept;
* a turn that finished its work is judged finished and cut;
* after a cut, back below the floor, nothing happens again;
* crossing again cuts again;
* what was cut can still be recalled from the ledger.

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

#: Low enough that a short session crosses it twice. The judge, the cut and
#: the ledger do not know what the floor is, only whether it has been passed.
FLOOR = 5

ARM = Arm(name="mechanism", description="", env={"TASKCUT": "1"}, config={"floorPercent": FLOOR})

#: A file of about fifteen thousand tokens, so that reading two of them moves a
#: million-token window across five percent.
_LINES = 700

#: What each file ends with, so that recall can be checked exactly.
LAST_LINES = {"notes2.txt": "KESTREL-41", "notes3.txt": "MARLIN-07"}
SECTION_3_FIRST = "PELICAN-93"

STEPS = [
    "Run `wc -l a.txt` and tell me the number.",
    "Read notes1.txt in full. Before you do anything with it, ask me which of its sections I care about.",
    "Section 3. Tell me its first line.",
    "Run `cat b.txt` and tell me the last word.",
    "Read notes2.txt in full and tell me its last line.",
    "Read notes3.txt in full and tell me its last line.",
    "Without running any tool: list every task I have given you in this conversation, with its result.",
]


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
    sections = []
    for n in range(1, 6):
        first = SECTION_3_FIRST if n == 3 else f"SECTION-{n}-OPENS"
        sections += [f"## Section {n}", first, *_filler(rng, _LINES // 5)]
    (root / "notes1.txt").write_text("\n".join(sections) + "\n")
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
    #: taskcut's own notices, one per judgement.
    verdicts: list[str] = field(default_factory=list)
    #: Tokens before each cut the turn ended with.
    cuts: list[int] = field(default_factory=list)
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
        elif kind == "system" and str(record.get("content") or "").startswith("taskcut:"):
            turn.verdicts.append(str(record.get("content")))
        elif kind == "assistant":
            usage, request = message.get("usage") or {}, record.get("requestId") or message.get("id")
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


def check(path: Path, window: int) -> list[Result]:
    """Every property the mechanism promises, asserted against one transcript."""
    work = [t for t in turns(path) if t.contexts]  # turns that ran, not re-emitted copies
    floor = window * FLOOR / 100
    # A whole percentage, compared as the plugin compares it: allow a point of
    # rounding either side rather than assert on the boundary itself.
    below = [t for t in work if t.carried < floor - window / 100]
    above = [t for t in work if t.carried >= floor + window / 100]
    step = {s: next((t for t in work if t.prompt.strip() == s), None) for s in STEPS}
    question, answered = step[STEPS[1]], step[STEPS[2]]
    last = work[-1] if work else Turn(prompt="")
    recall = " ".join(last.texts)
    wanted = ["3", SECTION_3_FIRST, "epsilon", *LAST_LINES.values()]
    cuts = [c for t in work for c in t.cuts]
    finished = [t for t in work if any("is finished" in v for v in t.verdicts)]
    skipped = [v for t in work for v in t.verdicts if "skipped" in v]
    closes = [c for t in work for c in t.closes]
    return [
        Result(
            "quiet below the floor",
            not any(t.active for t in below),
            f"{len(below)} turn(s) below the floor, {sum(t.active for t in below)} with any taskcut activity",
        ),
        Result(
            "every turn past the floor is judged",
            all(t.verdicts for t in above),
            f"{sum(bool(t.verdicts) for t in above)}/{len(above)} judged",
        ),
        Result(
            "a turn that ends in a question is kept",
            question is not None and any("not finished" in v for v in question.verdicts) and not question.cuts,
            "; ".join(question.verdicts) if question else "step not found",
        ),
        Result(
            "a finished turn is compacted",
            bool(finished) and all(t.cuts for t in finished) and answered in finished and not skipped,
            f"{len(finished)} judged finished, {sum(bool(t.cuts) for t in finished)} compacted, {len(skipped)} skipped",
        ),
        Result("nothing is compacted below the floor", all(c >= floor for c in cuts), f"compactions at {cuts}"),
        Result("crossing again compacts again", len(cuts) >= 2, f"{len(cuts)} compaction(s)"),
        Result(
            "what was compacted can be recalled",
            all(w in recall for w in wanted),
            "missing: " + ", ".join(w for w in wanted if w not in recall) if any(w not in recall for w in wanted) else "all six",
        ),
        Result(
            "the working model is never asked for anything",
            not closes and not any(t.searches or t.reminders for t in work),
            f"{len(closes)} close_task, {sum(t.searches for t in work)} ToolSearch, "
            f"{sum(t.reminders for t in work)} reminder(s)",
        ),
    ]
