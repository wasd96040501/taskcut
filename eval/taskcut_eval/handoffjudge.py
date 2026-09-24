"""The judge against the handoff labels: does it compact where the work could
have been handed over, and keep where it could not?

The labels come from ``handoff``: a model with hindsight read each session
whole. The judge is asked the same steps through the bench, with only what
taskcut gives it live. Judging every labelled step, several times over, would
cost hundreds of dollars a judge; most of them are COMPACT and say little. So
the steps asked are every KEEP step, a sample of the COMPACT ones, and the
first few candidates of every segment, in order -- enough to see where the
first compaction would have landed.

Every verdict is kept on disk under the judge's text and its model, so a run
asked again pays only for what it has not asked before. Sessions are the
person's own: nothing here is written inside the repository.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from . import handoff, judgebench, replay

#: A verdict that compacts, in either judge's words.
COMPACTS = frozenset({"COMPACT", "NEXT"})
#: Cases in one headless session: a crash loses no more than this.
CHUNK = 300


@dataclass
class Step:
    session: str
    segment: int
    n: int
    label: str
    context: int
    case: dict

    @property
    def id(self) -> str:
        return f"{self.session}#{self.n}"


def prepare(labels: Path, projects: Path, sets_dir: Path) -> tuple[list[Step], list[Path]]:
    """Every labelled step with the bench case that asks about it, and the
    replay sets the cases name: one per segment, as the bench reads a set
    whole and takes no file over 4 MiB."""
    rows = [json.loads(line) for line in labels.read_text().splitlines() if line.strip()]
    wanted = defaultdict(dict)
    for row in rows:
        if row.get("label"):
            wanted[row["session"]][row["step"]] = row["label"]
    sets_dir.mkdir(parents=True, exist_ok=True)
    set_paths: list[Path] = []
    steps: list[Step] = []
    for path in handoff.sessions(projects):
        if path.stem not in wanted:
            continue
        parsed = replay.parse(handoff._records(path))
        index = {}
        for s in parsed["steps"]:
            label = wanted[path.stem].get(s["n"])
            if label is None:
                continue
            key = (path.stem, s["segment"])
            if key not in index:
                target = sets_dir / f"{path.stem}--{s['segment']}.json"
                if not target.exists():
                    target.write_text(json.dumps({"segments": [parsed["segments"][s["segment"]]], "memory": []}))
                index[key] = len(set_paths)
                set_paths.append(target)
            case = {"id": f"{path.stem}#{s['n']}", "step": s["step"], "set": index[key], "segment": 0, "pos": s["end"]}
            steps.append(Step(path.stem, s["segment"], s["n"], label, s["context"], case))
    return steps, set_paths


def select(steps: list[Step], sample: int, head: int, seed: int = 0) -> list[Step]:
    """Every KEEP step, `sample` COMPACT ones, and each segment's first `head`
    candidates."""
    chosen = {s.id for s in steps if s.label == "KEEP"}
    compact = [s for s in steps if s.label == "COMPACT"]
    random.Random(seed).shuffle(compact)
    chosen |= {s.id for s in compact[:sample]}
    for group in segments(steps).values():
        chosen |= {s.id for s in group[:head]}
    return [s for s in steps if s.id in chosen]


def segments(steps: list[Step]) -> dict[tuple[str, int], list[Step]]:
    out: dict[tuple[str, int], list[Step]] = defaultdict(list)
    for s in steps:
        out[(s.session, s.segment)].append(s)
    return {k: sorted(v, key=lambda s: s.n) for k, v in out.items()}


def tag(judge: Path, harness: Path, model: str) -> str:
    """What a verdict was asked with: the judge's text, the bench's, the model."""
    digest = hashlib.sha256(judge.read_bytes() + (harness / "hooks" / "bench.ts").read_bytes()).hexdigest()[:12]
    return f"{digest}--{model}"


def cached(store: Path) -> dict[tuple[str, int], dict]:
    if not store.exists():
        return {}
    out = {}
    for line in store.read_text().splitlines():
        if line.strip():
            a = json.loads(line)
            out[(a["id"], a["run"])] = a
    return out


def ask(steps: list[Step], sets: list[Path], plugin: Path, scratch: Path, store: Path, model: str,
        repeats: int, concurrency: int, log=print) -> dict[tuple[str, int], dict]:
    """Each step `repeats` times, asking only what the store does not hold.
    A case missing any run is asked for all of them, and its runs renumbered
    after those already held."""
    have = cached(store)
    missing = [s for s in steps if any((s.id, r) not in have for r in range(repeats))]
    log(f"{len(steps)} steps, {len(steps) - len(missing)} already asked {repeats} times; asking {len(missing)}")
    for start in range(0, len(missing), CHUNK):
        chunk = missing[start:start + CHUNK]
        need = max(repeats - min(sum((s.id, r) in have for r in range(repeats)) for s in chunk), 1)
        answers = judgebench.ask([s.case for s in chunk], plugin, scratch, model, need, concurrency, sets=sets, timeout=6 * 3600)
        with store.open("a") as out:
            for a in sorted(answers, key=lambda a: (a["id"], a["run"])):
                runs = [r for r in range(repeats) if (a["id"], r) not in have]
                if not runs:
                    continue
                row = {k: a.get(k) for k in ("id", "verdict", "text", "usage", "ms", "attempts")} | {"run": runs[0]}
                have[(a["id"], runs[0])] = row
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        log(f"  {min(start + CHUNK, len(missing))}/{len(missing)} asked")
    return have


# --- scoring -----------------------------------------------------------------


def _interval(clusters: list[list[float]], draws: int = 2000, seed: int = 0) -> tuple[float, float]:
    """A 95% interval of a pooled rate, resampling sessions whole: steps of one
    session share its work, and are not independent."""
    clusters = [c for c in clusters if c]
    if not clusters:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        pool = [x for _ in clusters for x in rng.choice(clusters)]
        means.append(mean(pool))
    means.sort()
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def score(steps: list[Step], answers: dict[tuple[str, int], dict], model: str, repeats: int, head: int) -> list[str]:
    runs = {s.id: [answers[(s.id, r)] for r in range(repeats) if (s.id, r) in answers] for s in steps}
    asked = [s for s in steps if len(runs[s.id]) == repeats]
    compacts = {s.id: [a["verdict"] in COMPACTS for a in runs[s.id]] for s in asked}
    lines = [f"{len(asked)} steps from {len({s.session for s in asked})} sessions, {repeats} runs each, {model}"]

    def rate(label: str) -> str:
        members = [s for s in asked if s.label == label]
        by_session: dict[str, list[float]] = defaultdict(list)
        for s in members:
            by_session[s.session].append(mean(compacts[s.id]))
        if not members:
            return f"no {label} steps"
        lo, hi = _interval(list(by_session.values()))
        return f"{mean(x for v in by_session.values() for x in v):6.1%}  [{lo:.1%}, {hi:.1%}]  {len(members)} steps, {len(by_session)} sessions"

    lines.append(f"  compacts on KEEP     {rate('KEEP')}")
    lines.append(f"  compacts on COMPACT  {rate('COMPACT')}")
    lines.append(f"  compacts on UNSURE   {rate('UNSURE')}")
    agree = mean(len(set(v)) == 1 for v in compacts.values()) if compacts else float("nan")
    unanswered = sum(a["verdict"].startswith("unanswered") for v in runs.values() for a in v)
    every = [a for s in asked for a in runs[s.id]]
    dollars = sum(replay.price(model, a.get("usage")) for a in every)
    lines.append(f"  same verdict every run {agree:.1%}; unanswered {unanswered}; ${dollars:.2f} for {len(every)} calls, "
                 f"${dollars / max(len(every), 1):.4f} each")

    # Where the first compaction of a segment lands, run by run: the first
    # step judged COMPACT among its first `head` candidates, and what that step
    # was labelled. A segment with no such step keeps going past them.
    landed: dict[str, int] = defaultdict(int)
    delays, wasted = [], []
    for group in segments(asked).values():
        first = group[:head]
        if len(first) < min(head, len(group)) or any(s.id not in compacts for s in first):
            continue
        safe = next((i for i, s in enumerate(first) if s.label == "COMPACT"), None)
        for r in range(repeats):
            hit = next((i for i, s in enumerate(first) if compacts[s.id][r]), None)
            if hit is None:
                landed["none within the head" if len(group) > head else "none in the segment"] += 1
                continue
            landed[first[hit].label] += 1
            delays.append(hit)
            if safe is not None:
                wasted.append(hit - safe)
    total = sum(landed.values())
    lines.append(f"  first compaction of a segment, within its first {head} candidates ({total} segment-runs):")
    for key in ("COMPACT", "KEEP", "UNSURE", "none within the head", "none in the segment"):
        if landed[key]:
            lines.append(f"    on {key:<22} {landed[key] / total:6.1%}  ({landed[key]})")
    if delays:
        lines.append(f"    candidates past the first before it lands: mean {mean(delays):.2f}")
    if wasted:
        lines.append(f"    past the first one labelled COMPACT: mean {mean(wasted):.2f}")
    missed = sorted((s for s in asked if s.label == "KEEP" and any(compacts[s.id])), key=lambda s: -mean(compacts[s.id]))
    for s in missed[:30]:
        lines.append(f"  compacted a KEEP step {sum(compacts[s.id])}/{repeats}: {s.id}")
    return lines
