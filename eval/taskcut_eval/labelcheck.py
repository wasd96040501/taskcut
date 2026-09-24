"""Are the handoff labels right? Everything the judge is scored on rests on them.

Three checks, each a question with an answer in the record:

- The labeller again, blind: a sample of steps labelled afresh in calls of
  their own. Where it disagrees with itself, a label is noise.
- Another model, blind: the same steps labelled by a different model with the
  same instructions. Where two strong labellers split, the question itself is
  unclear there.
- Real compactions: the sessions were compacted for real, by Claude Code or by
  the person, and what the work did after is on record. A reviewer who is not
  shown the label says whether the work went on as well after the compaction.
  The step labelled nearest before it should be COMPACT where it did, KEEP
  where it did not. This is the handoff test with its outcome observed, not
  predicted.

Every call is cached as the labelling's are. Nothing is written in the repository.
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import handoff, replay

#: The other model, for the second blind labelling.
OTHER = "claude-fable-5-1"
#: Steps in one relabelling call: few, so that each is weighed on its own.
RELABEL_BATCH = 5

OUTCOME_SYSTEM = """You review a real coding session between a person and an AI assistant, at a point where the conversation was compacted: replaced by a summary, which the assistant then worked from. You are checking what that compaction cost the work.

The question: after the compaction, did the work that was open at that moment go on as well as it would have with the full conversation?

- HURT when, after the compaction, that work needed something the conversation had held and the summary dropped, and could not get it back cheaply: it redid an investigation, repeated an attempt that had already failed, re-ran something slow or re-queried a remote or changing system to recover what had been known, asked the person again for something they had already said, or went wrong for want of it.
- FINE when that work went on from the summary and the workspace. Getting detail back by reading a file again, or by quickly re-running a command that gives the same result, is fine.

Only the work that was open at the compaction counts. New work the person started afterwards does not.

The summary is the first thing in the text of the segment after the compaction; compare it with what the conversation before it held. Nothing is sent to anyone: you are reading a record. Look up the full text wherever the answer turns on it.

Output one JSON object and nothing else:
{"verdict": "HURT" | "FINE", "open": "<the work open at the compaction, at most 15 words>", "lost": "<what the summary dropped that the work then needed, or \\"nothing\\", at most 25 words>", "evidence": "<the steps after the compaction that show it, at most 30 words>"}"""


# --- the sample ----------------------------------------------------------------


def sample(rows: list[dict], per_label: int, cap: int, seed: int = 0) -> list[dict]:
    """`per_label` KEEP and as many COMPACT steps, at most `cap` of each from
    one session, so that no single long session speaks for the rest."""
    rng = random.Random(seed)
    out = []
    for label in ("KEEP", "COMPACT"):
        by_session: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            if r["label"] == label:
                by_session[r["session"]].append(r)
        pool = []
        for members in by_session.values():
            rng.shuffle(members)
            pool += members[:cap]
        rng.shuffle(pool)
        out += pool[:per_label]
    return out


def relabel_jobs(chosen: list[dict], projects: Path, work: Path, model: str, effort: str) -> list[handoff.Job]:
    """Calls that label the chosen steps again, a few at a time, from the same
    reading of the session the labelling had."""
    wanted: dict[tuple[str, int], list[int]] = defaultdict(list)
    for r in chosen:
        wanted[(r["session"], r["segment"])].append(r["step"])
    out = []
    for path in handoff.sessions(projects):
        if not any(s == path.stem for s, _ in wanted):
            continue
        heads = {}
        for job in handoff.jobs(path, work):
            heads.setdefault(job.segment, job)
        for (session, segment), steps in sorted(wanted.items()):
            if session != path.stem:
                continue
            job = heads[segment]
            head = job.prompt.rsplit(handoff.CANDIDATES, 1)[0]
            steps = sorted(steps)
            for i in range(0, len(steps), RELABEL_BATCH):
                batch = tuple(steps[i:i + RELABEL_BATCH])
                out.append(dataclasses.replace(job, steps=batch, model=model, effort=effort,
                                               prompt=head + handoff.CANDIDATES + "\n" + " ".join(f"#{n}" for n in batch)))
    return out


# --- real compactions --------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Boundary:
    session: str
    #: The segment the compaction ended, and its last step.
    segment: int
    last: int
    trigger: str
    #: The labelled step nearest before it, and its label.
    step: int
    label: str
    job: handoff.Job


def boundaries(projects: Path, work: Path, labels: dict[tuple[str, int], str], after: int = 10) -> list[Boundary]:
    """Every real compaction with a labelled step before it and at least
    `after` steps of work after it, and the call that reviews it."""
    out = []
    for path in handoff.sessions(projects):
        records = handoff._records(path)
        triggers = [(r.get("compactMetadata") or {}).get("trigger") or "?" for r in records
                    if r.get("type") == "system" and r.get("subtype") == "compact_boundary" and not r.get("isSidechain")]
        if not triggers:
            continue
        steps = replay.parse(records)["steps"]
        segs = handoff.segments(records, path.stem)
        texts = []
        for seg in segs:
            text = work / path.stem / f"{seg.index}.txt"
            text.parent.mkdir(parents=True, exist_ok=True)
            body = "\n".join(seg.full) + "\n"
            if not text.exists() or text.read_text() != body:
                text.write_text(body)
            texts.append(text)
        for b, trigger in enumerate(triggers):
            before = [s for s in steps if s["segment"] == b]
            later = [s for s in steps if s["segment"] == b + 1]
            labelled = [s for s in before if (path.stem, s["n"]) in labels]
            if not labelled or len(later) < after:
                continue
            last = before[-1]["n"]
            trail = handoff._compact_trail(segs[b].trail)
            after_trail = handoff._compact_trail(segs[b + 1].trail)
            prompt = "\n".join([
                f"Session {path.stem}. The conversation was compacted after step #{last}.",
                f"Full text of the conversation before the compaction, every command's output included: {texts[b]}",
                f"Full text after it, opening with the summary the compaction wrote: {texts[b + 1]}",
                "In a full text a step starts with a line `=== #<n> (context <c>%) ===`.",
                "",
                "--- before the compaction, one line a step (output left out) ---",
                *trail,
                "",
                "--- after it ---",
                *after_trail[: handoff.AFTER_STEPS],
            ])
            job = handoff.Job(path.stem, b, (last,), work / path.stem, prompt, (texts[b], texts[b + 1]), system=OUTCOME_SYSTEM)
            near = labelled[-1]["n"]
            out.append(Boundary(path.stem, b, last, trigger, near, labels[(path.stem, near)], job))
    return out


def review(job: handoff.Job, cache: Path) -> tuple[dict | None, float]:
    """The reviewer's answer for one compaction, from the cache when asked before."""
    cache.mkdir(parents=True, exist_ok=True)
    stored = cache / f"{job.key()}.json"
    if stored.exists():
        return json.loads(stored.read_text())["answer"], 0.0
    reply = handoff._ask(job)
    answer = None
    for m in re.finditer(r"\{[^{}]*\}", reply.get("result") or ""):
        try:
            row = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if row.get("verdict") in ("HURT", "FINE"):
            answer = row
    cost = float(reply.get("total_cost_usd") or 0)
    if answer and "error" not in reply and not reply.get("is_error"):
        stored.write_text(json.dumps({"session": job.session, "segment": job.segment, "cost": cost,
                                      "answer": answer, "result": reply.get("result", "")}, ensure_ascii=False))
    return answer, cost


def review_all(found: list[Boundary], cache: Path, workers: int, log=print) -> tuple[list[dict], float]:
    rows, spent = [], 0.0
    with ThreadPoolExecutor(workers) as pool:
        for i, (b, (answer, cost)) in enumerate(zip(found, pool.map(lambda b: review(b.job, cache), found)), 1):
            spent += cost
            rows.append({"session": b.session, "segment": b.segment, "last": b.last, "trigger": b.trigger,
                         "step": b.step, "label": b.label, **(answer or {"verdict": None})})
            log(f"[{i}/{len(found)}] {b.session[:8]} after #{b.last}: {(answer or {}).get('verdict')} (label {b.label}); ${spent:.2f} so far")
    return rows, spent


# --- agreement ---------------------------------------------------------------


def agreement(a: dict, b: dict) -> tuple[int, float, float, Counter]:
    """Over the keys both hold: how many, the share they agree on, Cohen's
    kappa, and the pairs (a's, b's)."""
    keys = [k for k in a if k in b]
    if not keys:
        return 0, float("nan"), float("nan"), Counter()
    pairs = Counter((a[k], b[k]) for k in keys)
    seen = sum(a[k] == b[k] for k in keys) / len(keys)
    values = {v for pair in pairs for v in pair}
    chance = sum((sum(n for (x, _), n in pairs.items() if x == v) / len(keys))
                 * (sum(n for (_, y), n in pairs.items() if y == v) / len(keys)) for v in values)
    kappa = (seen - chance) / (1 - chance) if chance < 1 else float("nan")
    return len(keys), seen, kappa, pairs
