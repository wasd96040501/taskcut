"""The judge replayed over real sessions: every step taskcut would have judged, labelled by hand.

`make eval-judge` asks the judge about sixteen steps written for it. This asks
it about the steps real sessions took -- every one taskcut would have judged,
as the session looked at that moment -- so that a change to what the judge
reads or is asked can be measured on the work it will actually see, and priced.

A **set** is one session's transcript turned into what `$.session.messages()`
held before each step, and the step itself: `eval/replay/<set>.json`, built by
`parse` and `judged` below and scrubbed of the home directory. It holds no tool
output: the judge never reads any, and the transcript's `toolResults` are kept
only as the fact that a message carried some.

Its **labels** are `eval/replay/<set>.labels`, one line per judged step:

    16 N  Issue 3 is done: the lineage walks both PIVOTs. Issue 4: ...

  N  the work moves on here from a finished piece to another the person asked for
  S  it does not
  E  either is defensible; left out of both rates

A **boundary** is a window: an N step and the E steps directly before it, which
belong to the same move ("Issue 22 done. Full-suite checkpoint:" and then
"Clean. Issue 23:"). It is caught when the judge says NEXT at any step of it --
live, the first NEXT compacts. What is measured, per repeat:

  boundaries   the share of windows caught
  false NEXT   the share of S steps called NEXT: a compaction in the middle of
               a piece, which costs re-reading what it threw away
  hard SAME    the share of S steps that say a piece passes or is done -- the
               judge's hardest SAME -- that it got right
  agreement    the share of labelled steps given the same verdict every repeat
  $            list price of what each call reported, and of the stretch of a
               long session past the floor

A miss costs a boundary that waits for the next one; a false NEXT costs a
compaction of work in flight. Both are small against a dollar -- a judgement
is half a cent -- so accuracy is the constraint and cost what is optimised.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

N, S, E = "N", "S", "E"

#: Lookups that change nothing. Must equal READ_ONLY_TOOLS in hooks/judge.ts;
#: a test holds them together.
READ_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "NotebookRead", "WebSearch", "ToolSearch"})

#: List price in dollars per million tokens, input and output, of the models a
#: judge runs on (Claude API, September 2026). A cache read is billed at
#: CACHE_READ and a write at CACHE_WRITE of the input price.
PRICES = {"sonnet": (2.0, 10.0), "haiku": (1.0, 5.0), "opus": (4.0, 20.0)}
CACHE_READ, CACHE_WRITE = 0.1, 1.25


# --- a transcript as the judge saw it ---------------------------------------


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def parse(lines) -> dict:
    """What `$.session.messages()` held before each main-thread step.

    A step is one model response: Claude Code writes one record per content
    block, all under the response's message id, and they are merged here into
    the step; the messages hold them a record at a time, as the engine does.
    A compaction starts a new segment, as it replaces the messages the engine
    holds: its summary, then the recent messages it preserved -- named in the
    boundary's `preservedMessages` -- then what follows. Sub-agents' records,
    and user records nobody sent (`isMeta`), are not part of the main
    conversation. A step's `index` counts from 0 in its turn, and a turn opens
    with any user message that is not a tool result or a compaction's summary.
    """
    segments: list[list[dict]] = [[]]
    steps: list[dict] = []
    by_id: dict[str, dict] = {}
    by_uuid: dict[str, dict] = {}
    preserved: list[dict] = []
    turn, index = -1, 0
    for line in lines:
        record = json.loads(line) if isinstance(line, str) else line
        kind = record.get("type")
        if record.get("isSidechain"):
            continue
        if kind == "system" and record.get("subtype") == "compact_boundary":
            kept = ((record.get("compactMetadata") or {}).get("preservedMessages") or {}).get("uuids") or []
            preserved = [by_uuid[u] for u in kept if u in by_uuid]
            segments.append([])
            by_id = {}
            continue
        if kind not in ("user", "assistant"):
            continue
        message = record.get("message") or {}
        messages = segments[-1]
        # The preserved messages follow the summary; anything else first
        # arriving means there was none.
        if preserved and not record.get("isCompactSummary"):
            messages.extend(dict(m) for m in preserved)
            preserved = []
        if kind == "user":
            blocks = _blocks(message.get("content"))
            results = [b for b in blocks if b.get("type") == "tool_result"]
            if results:
                held = {"role": "user", "text": "", "toolUses": [],
                        "toolResults": [{"tool_use_id": b.get("tool_use_id"), "text": ""} for b in results]}
                messages.append(held)
                by_uuid[record.get("uuid")] = held
                continue
            if record.get("isMeta"):
                continue
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if not text:
                continue
            held = {"role": "user", "text": text, "toolUses": []}
            messages.append(held)
            by_uuid[record.get("uuid")] = held
            if record.get("isCompactSummary"):
                messages.extend(dict(m) for m in preserved)
                preserved = []
            else:
                turn, index = turn + 1, 0
            continue
        mid = message.get("id")
        current = by_id.get(mid)
        if current is None:
            current = {"role": "assistant", "text": "", "toolUses": []}
            by_id[mid] = current
            usage = message.get("usage") or {}
            steps.append({
                # `pos`: where the step's own messages start; `end`: where
                # they stop, before any result of its calls. When the step is
                # judged the engine holds it: the judge is given up to `end`.
                "message": current, "segment": len(segments) - 1, "pos": len(messages), "end": len(messages),
                "turn": turn, "index": index, "stop_reason": None,
                "context": sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
            })
            index += 1
        # The engine holds a response as it records it, a record at a time --
        # its words one message, each call another -- and the judge counts
        # messages. The step is the response whole.
        held = {"role": "assistant", "text": "", "toolUses": []}
        for block in _blocks(message.get("content")):
            if block.get("type") == "text" and block.get("text", "").strip():
                current["text"] = (current["text"] + "\n" + block["text"]).strip()
                held["text"] = (held["text"] + "\n" + block["text"]).strip()
            elif block.get("type") == "tool_use":
                use = {"tool_use_id": block.get("id"), "tool": block.get("name"), "input": block.get("input")}
                current["toolUses"].append(use)
                held["toolUses"].append(use)
        if held["text"] or held["toolUses"]:
            messages.append(held)
            by_uuid[record.get("uuid")] = held
            for step in reversed(steps):
                if step["message"] is current:
                    step["end"] = len(messages)
                    break
        if message.get("stop_reason"):
            for step in reversed(steps):
                if step["message"] is current:
                    step["stop_reason"] = message["stop_reason"]
                    break
    out = []
    for n, step in enumerate(steps):
        m = step.pop("message")
        out.append({"n": n, **step, "step": {"text": m["text"], "calls": [{"name": u["tool"], "input": u["input"]} for u in m["toolUses"]]}})
    return {"segments": segments, "steps": out}


def acts(calls) -> bool:
    return any(c["name"] not in READ_ONLY_TOOLS for c in calls)


def judged(replay: dict) -> list[int]:
    """The steps taskcut would have judged, the floor aside: hooks/register.ts's
    rule. A step that ends the turn is not; nor the first of a turn, whose
    request ended on the person's own words; nor one with nothing to say; nor
    any after a compaction until a step has changed something. Every compaction
    in a benchmark session is taskcut's, which is the only kind that resets
    the last, and the floor is left out so that every step can be asked about;
    `context` says which were past it."""
    out = []
    acted_since, segment = True, 0
    for s in replay["steps"]:
        if s["segment"] != segment:
            segment, acted_since = s["segment"], False
        acted = acted_since
        if acts(s["step"]["calls"]):
            acted_since = True
        if s["stop_reason"] == "tool_use" and acted and s["index"] > 0 and s["step"]["text"].strip():
            out.append(s["n"])
    return out


def scrub(value, home: str):
    """Every string with the home directory put as `~`, as a path and as Claude
    Code spells it in a directory name (`-Users-me-`): a set is committed."""
    if isinstance(value, str):
        return value.replace(home, "~").replace(home.replace("/", "-"), "-~")
    if isinstance(value, list):
        return [scrub(v, home) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v, home) for k, v in value.items()}
    return value


def build(transcript: Path, name: str, source: str, home: str, memory: list[str] = ()) -> dict:
    replay = parse(transcript.read_text().splitlines())
    return scrub({"name": name, "source": source, "memory": list(memory), "judged": judged(replay), **replay}, home)


# --- labels ------------------------------------------------------------------

LABEL_LINE = re.compile(r"^(\d+)\s+([NSE?])(?:\s|$)")


def excerpt(text: str, limit: int = 160) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 1] + "…"


def labels_template(replay: dict, header: str, known: dict[int, str] | None = None) -> str:
    """A labels file for a set: one line per judged step, `?` where unknown."""
    by_n = {s["n"]: s for s in replay["steps"]}
    lines = [f"# {line}" if line else "#" for line in header.splitlines()]
    for n in replay["judged"]:
        lines.append(f"{n:<4} {(known or {}).get(n, '?')}  {excerpt(by_n[n]['step']['text'])}")
    return "\n".join(lines) + "\n"


def read_labels(text: str) -> dict[int, str]:
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = LABEL_LINE.match(line)
        if not m:
            raise ValueError(f"not a label line: {line!r}")
        n = int(m[1])
        if n in out:
            raise ValueError(f"step {n} labelled twice")
        out[n] = m[2]
    return out


def check_labels(replay: dict, labels: dict[int, str]) -> list[str]:
    """Every judged step labelled N, S or E, and nothing else labelled."""
    problems = []
    judged_steps = set(replay["judged"])
    if missing := sorted(judged_steps - set(labels)):
        problems.append(f"{replay['name']}: judged steps with no label: {missing}")
    if extra := sorted(set(labels) - judged_steps):
        problems.append(f"{replay['name']}: labelled steps it would not judge: {extra}")
    if unsure := sorted(n for n, v in labels.items() if v not in (N, S, E)):
        problems.append(f"{replay['name']}: steps still to label: {unsure}")
    return problems


def windows(labels: dict[int, str]) -> list[list[int]]:
    """Each N step with the E steps directly before it."""
    ids = sorted(labels)
    out = []
    for i, n in enumerate(ids):
        if labels[n] != N:
            continue
        window, j = [n], i - 1
        while j >= 0 and labels[ids[j]] == E:
            window.insert(0, ids[j])
            j -= 1
        out.append(window)
    return out


def kappa(a: dict[int, str], b: dict[int, str]) -> float:
    """Cohen's kappa of two labellings over the steps both labelled: their
    agreement beyond what their label frequencies alone would give."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return float("nan")
    observed = mean(a[n] == b[n] for n in shared)
    expected = sum(mean(a[n] == c for n in shared) * mean(b[n] == c for n in shared) for c in (N, S, E))
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


# --- scoring -----------------------------------------------------------------

#: A step that says, in words, that something passes or is done. When such a
#: step is labelled S -- the last piece done, a piece passing but still being
#: checked, a recap -- saying SAME is the judge's hardest right answer.
CLAIMS = re.compile(r"\b(pass(es|ed|ing)?|done|fixed|complete[d]?|finished|confirmed)\b|完成|已推送|改完|通过|修好", re.I)


@dataclass
class Verdict:
    next: bool
    answered: bool
    cost: float
    tokens_in: int
    tokens_out: int
    ms: int = 0


@dataclass
class Scores:
    boundaries: float
    false_next: float
    hard_same: float
    agreement: float
    unanswered: int
    calls: int
    dollars: float
    per_judgement: float
    tokens_in: float
    tokens_out: float
    p50_ms: float
    windows: int
    same_steps: int
    repeats: int
    #: Per set: (windows caught, windows asked, S called NEXT, S asked), summed over repeats.
    by_set: dict = field(default_factory=dict)
    missed: list = field(default_factory=list)
    wrong_next: list = field(default_factory=list)


def price(model: str, usage: dict | None) -> float:
    if not usage:
        return 0.0
    key = next((k for k in PRICES if k in model), None)
    if key is None:
        raise KeyError(f"no list price for {model!r}; add it to PRICES")
    pin, pout = PRICES[key]
    return (usage.get("input_tokens", 0) * pin + usage.get("cache_read_input_tokens", 0) * pin * CACHE_READ
            + usage.get("cache_creation_input_tokens", 0) * pin * CACHE_WRITE + usage.get("output_tokens", 0) * pout) / 1e6


def verdicts(answers: list[dict], model: str) -> dict[str, list[Verdict]]:
    """The bench's answers by case id, in repeat order. An unanswered call is
    SAME, as it is live: taskcut keeps the context when it has no answer."""
    out: dict[str, list[Verdict]] = defaultdict(list)
    for a in sorted(answers, key=lambda a: (a["id"], a["run"])):
        usage = a.get("usage") or {}
        out[a["id"]].append(Verdict(
            next=a["verdict"] == "NEXT", answered=not a["verdict"].startswith("unanswered"), cost=price(model, usage),
            tokens_in=sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
            tokens_out=usage.get("output_tokens", 0), ms=a.get("ms", 0)))
    return out


def score(sets: dict[str, dict], labels: dict[str, dict[int, str]], answers: dict[str, list[Verdict]]) -> Scores:
    """`answers` by case id, `<set>#<step>`, one verdict per repeat. Only the
    sets in `labels` are scored, and only their calls counted and priced."""
    answers = {k: v for k, v in answers.items() if k.split("#")[0] in labels}
    repeats = min(len(v) for v in answers.values())
    caught = []
    false = []
    hard = []
    by_set = {}
    missed, wrong = [], []
    for name, marks in labels.items():
        steps = {s["n"]: s for s in sets[name]["steps"]}
        ws = windows(marks)
        same = [n for n, v in marks.items() if v == S]
        c = sum(any(answers[f"{name}#{n}"][r].next for n in w) for w in ws for r in range(repeats))
        f = sum(answers[f"{name}#{n}"][r].next for n in same for r in range(repeats))
        by_set[name] = (c, len(ws) * repeats, f, len(same) * repeats)
        for w in ws:
            hits = sum(any(answers[f"{name}#{n}"][r].next for n in w) for r in range(repeats))
            caught.append(hits / repeats)
            if hits < repeats:
                missed.append((name, w, repeats - hits, excerpt(steps[w[-1]]["step"]["text"])))
        for n in same:
            called = sum(answers[f"{name}#{n}"][r].next for r in range(repeats))
            false.append(called / repeats)
            if called:
                wrong.append((name, n, called, excerpt(steps[n]["step"]["text"])))
            if CLAIMS.search(steps[n]["step"]["text"]):
                hard.append(1 - called / repeats)
    labelled = [answers[f"{name}#{n}"][:repeats] for name, marks in labels.items() for n, v in marks.items() if v != E]
    every = [v for vs in answers.values() for v in vs[:repeats]]
    return Scores(
        boundaries=mean(caught) if caught else float("nan"),
        false_next=mean(false) if false else float("nan"),
        hard_same=mean(hard) if hard else float("nan"),
        agreement=mean(len({v.next for v in vs}) == 1 for vs in labelled) if labelled else float("nan"),
        unanswered=sum(not v.answered for v in every),
        calls=len(every),
        dollars=sum(v.cost for v in every),
        per_judgement=mean(v.cost for v in every),
        tokens_in=mean(v.tokens_in for v in every),
        tokens_out=mean(v.tokens_out for v in every),
        p50_ms=median(v.ms for v in every),
        windows=len(caught),
        same_steps=len(false),
        repeats=repeats,
        by_set=by_set,
        missed=missed,
        wrong_next=wrong,
    )


def stretch(sets: dict[str, dict], answers: dict[str, list[Verdict]], name: str, floor_tokens: int) -> tuple[float, int]:
    """What judging every judged step of one set past a floor would cost, per
    pass: the realistic bill, since only past the floor is anything judged."""
    ids = [n for n in sets[name]["judged"] if next(s for s in sets[name]["steps"] if s["n"] == n)["context"] >= floor_tokens]
    runs = [answers[f"{name}#{n}"] for n in ids if f"{name}#{n}" in answers]
    if not runs:
        return 0.0, 0
    repeats = min(len(v) for v in runs)
    return mean(sum(v[r].cost for v in runs) for r in range(repeats)), len(ids)


def units(labels: dict[str, dict[int, str]], answers: dict[str, list[Verdict]]) -> tuple[list, list]:
    """The units the two rates are means of, per repeat: one per boundary
    window (caught or not) and one per S step (called NEXT or not)."""
    repeats = min(len(v) for v in answers.values())
    caught, false = [], []
    for name, marks in labels.items():
        for w in windows(marks):
            caught.append([any(answers[f"{name}#{n}"][r].next for n in w) for r in range(repeats)])
        for n, v in marks.items():
            if v == S:
                false.append([answers[f"{name}#{n}"][r].next for r in range(repeats)])
    return caught, false


def interval(values: list[list[bool]], draws: int = 2000, seed: int = 0) -> tuple[float, float]:
    """A 95% bootstrap interval of a rate, resampling units (boundaries, or S
    steps) with their repeats: the repeats of one step are not independent
    samples of the judge, and treating them as such would narrow it."""
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = sorted(mean(mean(rng.choice(values)) for _ in values) for _ in range(draws))
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def paired(a: list[list[bool]], b: list[list[bool]], draws: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """The difference of a rate, b minus a, over the same units, with a 95%
    bootstrap interval resampling the units both were asked about."""
    diffs = [mean(y) - mean(x) for x, y in zip(a, b, strict=True)]
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    means = sorted(mean(rng.choice(diffs) for _ in diffs) for _ in range(draws))
    return mean(diffs), means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


# --- sets on disk, and the run ----------------------------------------------


def load_sets(directories: list[Path], names=()) -> tuple[dict[str, dict], dict[str, dict[int, str]], dict[str, Path]]:
    """Every set with a labels file beside it, or the ones named. A set in
    `local/` is one that cannot be published -- someone's own session -- and
    is read the same way when it is there."""
    sets, labels, paths = {}, {}, {}
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            name = path.stem
            if names and name not in names:
                continue
            marks = path.with_suffix(".labels")
            if not marks.exists():
                continue
            sets[name] = json.loads(path.read_text())
            labels[name] = read_labels(marks.read_text())
            paths[name] = path
    if names and (unknown := sorted(set(names) - set(sets))):
        raise SystemExit(f"no labelled set named {unknown}")
    problems = [p for name in sets for p in check_labels(sets[name], labels[name])]
    if problems:
        raise SystemExit("labels do not cover the steps taskcut judges:\n  " + "\n  ".join(problems))
    return sets, labels, paths


def cases(sets: dict[str, dict], labels: dict[str, dict[int, str]], order: list[str]) -> list[dict]:
    """One bench case per labelled step, naming its set by position in `order`."""
    out = []
    for name, marks in labels.items():
        steps = {s["n"]: s for s in sets[name]["steps"]}
        for n in sorted(marks):
            s = steps[n]
            # The messages the engine holds when the step is judged: the step's
            # own among them, before its calls have run. A judge must leave
            # them out itself, as it must live.
            out.append({"id": f"{name}#{n}", "step": s["step"], "set": order.index(name), "segment": s["segment"], "pos": s["end"]})
    return out


def _pct(x: float) -> str:
    return "-" if x != x else f"{x:.1%}"


def render(label: str, s: Scores, caught_ci, false_ci, stretch_cost: tuple[float, int] | None) -> str:
    lines = [
        f"## {label}: {s.windows} boundaries, {s.same_steps} steps that are not one, {s.repeats} repeats, {s.calls} calls",
        "",
        f"  boundaries caught  {_pct(s.boundaries):>7}   95% {_pct(caught_ci[0])} - {_pct(caught_ci[1])}",
        f"  false NEXT         {_pct(s.false_next):>7}   95% {_pct(false_ci[0])} - {_pct(false_ci[1])}",
        f"  hard SAME right    {_pct(s.hard_same):>7}",
        f"  same every repeat  {_pct(s.agreement):>7}",
        f"  unanswered         {s.unanswered:>7}",
        f"  $ per judgement    {s.per_judgement:>9.5f}   ({s.tokens_in:,.0f} tokens in, {s.tokens_out:,.0f} out, p50 {s.p50_ms / 1000:.1f}s)",
        f"  $ this run         {s.dollars:>9.2f}",
    ]
    if stretch_cost and stretch_cost[1]:
        lines.append(f"  $ past the floor   {stretch_cost[0]:>9.4f}   (sqlglot-long--off past 35% of 1M: {stretch_cost[1]} judged steps, one pass)")
    lines += ["", "  per set: boundaries caught / asked, false NEXT / S steps asked (summed over repeats)"]
    for name, (c, cw, f, fs) in s.by_set.items():
        lines.append(f"    {name:<28} {c:>4}/{cw:<4}  {f:>3}/{fs:<4}")
    if s.missed:
        lines += ["", "  boundaries missed (times missed: the step)"]
        lines += [f"    {k}x {name}#{w}: {text}" for name, w, k, text in s.missed]
    if s.wrong_next:
        lines += ["", "  called NEXT where it is not (times: the step)"]
        lines += [f"    {k}x {name}#{n}: {text}" for name, n, k, text in s.wrong_next]
    return "\n".join(lines)


def sheet(replay: dict, labels: dict[int, str], context: int = 3) -> str:
    """A set's judged steps as a reviewer needs them, to label or to check a
    label: what the person last asked, what the assistant said just before,
    and the step -- its words and what its calls touched."""
    by_n = {s["n"]: s for s in replay["steps"]}
    out = [f"# {replay['name']}", "", replay.get("source", ""), ""]
    previous = -1
    for n in replay["judged"]:
        s = by_n[n]
        # What happened since the last step asked about, much of it in steps
        # that said nothing: a commit, the next issue opened.
        between = [by_n[k] for k in range(previous + 1, n) if k in by_n]
        previous = n
        before = replay["segments"][s["segment"]][: s["pos"]]
        asked = [m["text"] for m in before if m["role"] == "user" and not m.get("toolResults")]
        said = [m["text"] for m in before if m["role"] == "assistant" and m["text"].strip()][-context:]
        out += [f"## step {n}   label: {labels.get(n, '?')}", ""]
        for k, text in enumerate(asked):
            out.append(f"**Request {k + 1} of {len(asked)}:** {excerpt(text, 900 if k == 0 else 300)}")
        if asked:
            out.append("")
        for text in said:
            out.append(f"> before: {excerpt(text, 300)}")
        if between:
            out += ["", f"Since the last step asked about, {len(between)} step(s):"]
            for b in between:
                words = f'"{excerpt(b["step"]["text"], 120)}" ' if b["step"]["text"].strip() else ""
                out.append(f"- step {b['n']}: {words}{'; '.join(_call(c, 90) for c in b['step']['calls']) or '(no calls)'}")
        out += ["", f"**Step:** {s['step']['text'].strip()}", ""]
        for call in s["step"]["calls"]:
            out.append(f"- calls {_call(call, 160)}")
        out.append("")
    return "\n".join(out)


def _call(call: dict, limit: int) -> str:
    fields = call["input"] if isinstance(call["input"], dict) else {}
    what = fields.get("file_path") or fields.get("description") or fields.get("subject") or fields.get("command") or json.dumps(call["input"])
    if call["name"] == "TaskUpdate":
        what = f"task {fields.get('taskId')} -> {fields.get('status')}"
    return f"{call['name']}: {excerpt(str(what), limit)}"
