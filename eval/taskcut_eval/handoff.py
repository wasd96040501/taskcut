"""Handoff labels: at each step taskcut would judge, could the work have been handed over?

The judge is asked one thing at a step: if the conversation were compacted now
and the work handed to a colleague holding only the summary and the workspace,
would every piece of work still open be carried on as well? This labels that
question on real sessions, with hindsight, so that a judge which has only the
moment can be scored against what turned out to be true.

A segment -- the conversation from one compaction to the next -- runs to
hundreds of thousands of tokens once it is past the floor, and most of it is
command output the label seldom turns on. So the labeller is not handed it
whole. Its prompt holds the segment and what came after it as a trail --
every request, what each step said and what its calls touched, no output --
and the full text, every output included, sits in files beside it for the
labeller to read or search when a label turns on what a command printed. It
labels a batch of a segment's steps in one call, over the same prompt prefix.

Every call is cached on disk under a key of everything it was given, so a
labelling that is run again pays only for what changed. Sessions are the
person's own: nothing here is written inside the repository.
"""

from __future__ import annotations

import dataclasses
import glob
import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import replay

#: The labeller, and how hard it thinks.
MODEL = "claude-opus-5-5"
EFFORT = "medium"
#: Where taskcut starts judging on a 1M window at its default floor of 35%.
FLOOR = 350_000
#: Candidates labelled in one call. Neighbouring steps share their open work,
#: so a batch is labelled from one reading of the segment.
BATCH = 40
#: How much of one command's output the full text keeps: its head and its tail.
OUTPUT_HEAD, OUTPUT_TAIL = 12_000, 6_000
CALL_LIMIT = 2_000
#: The trail after a segment: enough to see whether later work drew on it.
AFTER_STEPS = 400
#: The line that ends a prompt's shared head and starts its list of steps.
CANDIDATES = "--- candidate steps to label ---"

SYSTEM = """You label moments in a real coding session between a person and an AI assistant, for an evaluation of a component that decides when to compact the conversation.

Compacting replaces the conversation with a summary. The summary keeps what the person asked for, the decisions and conclusions reached, which files were changed, and the work in progress. It drops how the work got there: the contents of files that were read, the output of commands, attempts that failed, and the reasoning along the way.

At each candidate step, apply the handoff test: suppose that, once the step's calls had run, the work were handed to a capable colleague who gets only that summary and the workspace -- the repository and anything saved to files, which they can read again. Would they carry on every piece of work still open as well as the assistant did with the full conversation?

Work is open until it is finished and nothing more is expected of it. A piece just finished is still open while the person has not reacted to it. Work set aside for a side question is still open.

You have hindsight: you can see what happened after each step. Use it. The label is what turned out to be true, not what could be predicted at the time.
- KEEP when some open work went on to need detail from before the step that the summary drops and that cannot be got back cheaply: output a quick re-run would not reproduce (a long run, a remote or changing system, a one-off experiment), what a query or an investigation found, why an approach failed, what was read somewhere that is not in the repository.
- COMPACT when the open work went on needing only conclusions, or detail the colleague could get back cheaply: reading a file again, or re-running a quick command that gives the same result.
- UNSURE only when the session does not show which. Use it sparingly.

"As well" means as well, not eventually. Redoing an investigation, repeating a failed attempt, or re-running something slow to recover what was already known counts against compacting.

Nothing is sent to anyone: you are reading a record. Look up the full text when a label turns on it -- whether a later step relied on something a command printed earlier, or whether a finding was ever written down.

For every candidate step, output one JSON object on its own line, and nothing else:
{"step": <n>, "label": "COMPACT" | "KEEP" | "UNSURE", "open": "<the work still open, at most 15 words>", "evidence": "<what decides it, at most 30 words>"}"""


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def _one(text: str) -> str:
    return " ".join(text.split())


def _cut(text: str, limit: int) -> str:
    text = _one(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _ends(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n[... {len(text) - head - tail:,} characters left out ...]\n{text[-tail:]}"


def _output(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for b in _blocks(content):
        parts.append(b.get("text", "") if b.get("type") == "text" else f"[{b.get('type', 'block')}]")
    return "\n".join(parts)


def _touched(name: str, value) -> str:
    fields = value if isinstance(value, dict) else {}
    if isinstance(fields.get("file_path"), str):
        return f"{name} {fields['file_path']}"
    if name == "Bash":
        return "Bash: " + _cut(str(fields.get("description") or fields.get("command") or ""), 100)
    return f"{name}: " + _cut(json.dumps(value, ensure_ascii=False), 80)


@dataclass
class Segment:
    """One stretch of a session between compactions, as the labeller reads it."""
    session: str
    index: int
    #: The full text, every output included, and the trail, which leaves them out.
    full: list[str] = field(default_factory=list)
    trail: list[str] = field(default_factory=list)
    #: The summary the compaction that ended this segment wrote, if one did.
    summary: str = ""


def segments(records: list[dict], session: str) -> list[Segment]:
    """The session's segments. Steps are numbered as `replay.parse` numbers
    them -- one per response, counted across the session -- so that a label
    names the same step the judge replay asks about."""
    out = [Segment(session, 0)]
    by_id: dict[str, int] = {}
    n = -1
    for r in records:
        if r.get("isSidechain"):
            continue
        kind = r.get("type")
        if kind == "system" and r.get("subtype") == "compact_boundary":
            out.append(Segment(session, len(out)))
            by_id = {}
            continue
        if kind not in ("user", "assistant"):
            continue
        seg = out[-1]
        message = r.get("message") or {}
        if kind == "user":
            blocks = _blocks(message.get("content"))
            results = [b for b in blocks if b.get("type") == "tool_result"]
            if results:
                for b in results:
                    seg.full.append(f"--- output of [{b.get('tool_use_id')}] ---")
                    seg.full.append(_ends(_output(b), OUTPUT_HEAD, OUTPUT_TAIL))
                continue
            if r.get("isMeta"):
                continue
            text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            if not text:
                continue
            if r.get("isCompactSummary"):
                # It opens the segment after the compaction that wrote it.
                if len(out) > 1:
                    out[-2].summary = text
                seg.full += ["=== Summary the compaction wrote of the conversation before ===", text]
                seg.trail.append(f"(summary of the conversation before, written by the compaction: {_cut(text, 1500)})")
            else:
                seg.full += ["=== Person ===", text]
                seg.trail.append(f"PERSON: {_cut(text, 1500)}")
            continue
        mid = message.get("id")
        if mid not in by_id:
            n += 1
            by_id[mid] = n
            usage = message.get("usage") or {}
            context = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            seg.full.append(f"=== #{n} (context {context // 10_000}%) ===")
            seg.trail.append(f"#{n} [{context // 10_000}%]")
        step = by_id[mid]
        for b in _blocks(message.get("content")):
            if b.get("type") == "text" and b.get("text", "").strip():
                seg.full.append(f"Assistant: {b['text'].strip()}")
                seg.trail.append(f"#{step} says: {_cut(b['text'], 300)}")
            elif b.get("type") == "tool_use":
                seg.full.append(f"Call {b.get('name')} [{b.get('id')}]: {_cut(json.dumps(b.get('input'), ensure_ascii=False), CALL_LIMIT)}")
                seg.trail.append(f"#{step} calls {_touched(b.get('name', ''), b.get('input'))}")
    return out


def _compact_trail(lines: list[str]) -> list[str]:
    """The trail with a step's lines joined, so it reads one line a step."""
    out: list[str] = []
    for line in lines:
        m = re.match(r"#(\d+) (says: |calls )(.*)", line)
        if m and out and out[-1].startswith(f"#{m.group(1)} "):
            out[-1] += (" | " if m.group(2) == "says: " else " || ") + m.group(3)
        elif m:
            out.append(f"#{m.group(1)} " + m.group(3))
        else:
            out.append(line)
    return out


@dataclass(frozen=True)
class Job:
    session: str
    segment: int
    steps: tuple[int, ...]
    directory: Path
    prompt: str

    #: The full texts the prompt points at: this segment's and the ones after it.
    files: tuple[Path, ...] = ()
    #: Who is asked, and what they are told: the labeller, unless a check asks another.
    model: str = MODEL
    effort: str = EFFORT
    system: str = SYSTEM

    def key(self) -> str:
        digests = [hashlib.sha256(f.read_bytes()).hexdigest() for f in self.files]
        blob = json.dumps([self.model, self.effort, self.system, self.prompt, digests])
        return hashlib.sha256(blob.encode()).hexdigest()


def sessions(projects: Path, floor: int = FLOOR) -> list[Path]:
    """The person's main-thread transcripts that got past the floor, the
    benchmark's own sessions left out."""
    found = []
    for path in sorted(glob.glob(str(projects / "*" / "*.jsonl"))):
        if "taskcut-eval" in path:
            continue
        peak = 0
        with open(path, errors="replace") as f:
            for line in f:
                if '"usage"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("type") == "assistant" and not r.get("isSidechain"):
                    u = (r.get("message") or {}).get("usage") or {}
                    peak = max(peak, sum(u.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
        if peak >= floor:
            found.append(Path(path))
    return found


def _records(path: Path) -> list[dict]:
    out = []
    with open(path, errors="replace") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def jobs(path: Path, work: Path, floor: int = FLOOR) -> list[Job]:
    """The calls that label one session: its candidate steps -- every step
    taskcut would judge, past the floor -- in batches, per segment."""
    records = _records(path)
    parsed = replay.parse(records)
    steps = {s["n"]: s for s in parsed["steps"]}
    candidates = [n for n in replay.judged(parsed) if steps[n]["context"] >= floor]
    if not candidates:
        return []
    segs = segments(records, path.stem)
    # Each segment's full text is written once; a prompt points at its own and
    # at the ones after it that its trail of later work reaches.
    texts = []
    for seg in segs:
        text = work / path.stem / f"{seg.index}.txt"
        text.parent.mkdir(parents=True, exist_ok=True)
        text.write_text("\n".join(seg.full) + "\n")
        texts.append(text)
    out = []
    for seg in segs:
        mine = [n for n in candidates if steps[n]["segment"] == seg.index]
        if not mine:
            continue
        after_lines: list[str] = []
        reached = []
        for later in segs[seg.index + 1:]:
            if sum(1 for line in after_lines if re.match(r"#\d+ ", line)) >= AFTER_STEPS:
                after_lines.append("(the session goes on; left out)")
                break
            after_lines += _compact_trail(later.trail)
            reached.append(texts[later.index])
        head = [
            f"Session {path.stem}, segment {seg.index}: the conversation from "
            + ("its start" if seg.index == 0 else "a compaction") + " to "
            + ("a compaction" if seg.index + 1 < len(segs) else "the end of the session") + ".",
            f"Full text of this segment, every command's output included: {texts[seg.index]}",
            *(["Full text of the segments after it, in order: " + ", ".join(str(t) for t in reached)] if reached else []),
            "In a full text a step starts with a line `=== #<n> (context <c>%) ===`.",
            "",
            "--- this segment, one line a step (output left out; [c%] is how full the context was) ---",
            *_compact_trail(seg.trail),
            "",
            "--- what came after this segment ---",
            *(after_lines or ["(nothing: the session ends here)"]),
            "",
        ]
        files = (texts[seg.index], *reached)
        for i in range(0, len(mine), BATCH):
            batch = tuple(mine[i:i + BATCH])
            prompt = "\n".join(head + [CANDIDATES, " ".join(f"#{n}" for n in batch)])
            out.append(Job(path.stem, seg.index, batch, work / path.stem, prompt, files))
    return out


def _ask(job: Job) -> dict:
    command = ["claude", "-p", "--model", job.model, "--effort", job.effort, "--system-prompt", job.system,
               "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob",
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--output-format", "json"]
    done = subprocess.run(command, input=job.prompt, capture_output=True, text=True, cwd=job.directory,
                          timeout=3600, env={**os.environ, "TASKCUT": "0"})
    try:
        reply = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {"error": (done.stderr or done.stdout)[-2000:]}
    return reply


def _labels(text: str, wanted: tuple[int, ...]) -> dict[int, dict]:
    out = {}
    for m in re.finditer(r"\{[^{}]*\}", text or ""):
        try:
            row = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        step = row.get("step")
        if isinstance(step, str):
            step = int(step.lstrip("#")) if step.lstrip("#").isdigit() else None
        if step in wanted and row.get("label") in ("COMPACT", "KEEP", "UNSURE"):
            out[step] = row
    return out


def run(job: Job, cache: Path) -> tuple[dict[int, dict], float, bool]:
    """Labels for one job: from the cache when this exact call was made
    before, from the model otherwise. Returns the labels, what the call cost,
    and whether it came from the cache."""
    cache.mkdir(parents=True, exist_ok=True)
    stored = cache / f"{job.key()}.json"
    if stored.exists():
        record = json.loads(stored.read_text())
        return {int(k): v for k, v in record["labels"].items()}, 0.0, True
    reply = _ask(job)
    labels = _labels(reply.get("result", ""), job.steps)
    cost = float(reply.get("total_cost_usd") or 0)
    # A reply that labelled nothing is not kept: asked again, the same call
    # would come back from the cache.
    if labels and "error" not in reply and not reply.get("is_error"):
        stored.write_text(json.dumps({"session": job.session, "segment": job.segment, "steps": job.steps,
                                      "model": MODEL, "effort": EFFORT, "cost": cost, "turns": reply.get("num_turns"),
                                      "labels": labels, "result": reply.get("result", "")}, ensure_ascii=False))
    return labels, cost, False


def label(all_jobs: list[Job], cache: Path, workers: int, log=print) -> tuple[list[dict], float]:
    """Every job, `workers` at a time. A step a reply left out is asked about
    again, alone in a job of its own, once."""
    rows: list[dict] = []
    spent = 0.0

    def one(job: Job):
        labels, cost, cached = run(job, cache)
        missing = tuple(n for n in job.steps if n not in labels)
        if missing:
            retry = dataclasses.replace(job, steps=missing, prompt=job.prompt.rsplit(CANDIDATES, 1)[0]
                                        + CANDIDATES + "\n" + " ".join(f"#{n}" for n in missing))
            more, extra, _ = run(retry, cache)
            labels.update(more)
            cost += extra
        return job, labels, cost, cached

    with ThreadPoolExecutor(workers) as pool:
        for i, (job, labels, cost, cached) in enumerate(pool.map(one, all_jobs), 1):
            spent += cost
            for n in job.steps:
                row = labels.get(n)
                rows.append({"session": job.session, "segment": job.segment, "step": n,
                             **({k: row.get(k) for k in ("label", "open", "evidence")} if row else {"label": None})})
            got = sum(n in labels for n in job.steps)
            log(f"[{i}/{len(all_jobs)}] {job.session[:8]} segment {job.segment}: {got}/{len(job.steps)} labelled"
                f"{' (cached)' if cached else f', ${cost:.2f}'}; ${spent:.2f} so far")
    return rows, spent
