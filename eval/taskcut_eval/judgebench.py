"""The judge on its own: labelled steps, asked through the call taskcut makes.

The mechanism check and the workloads show what the judge does inside a real
session, where every verdict costs a session to reproduce. This asks it about
the steps in ``judgecases`` directly, several times each, so that a change to
the question can be measured against the same cases before and after.

It runs in a headless session: ``$.model.complete`` works there, and nothing
here compacts. The harness plugin in ``eval/judge`` is copied beside a copy of
the plugin's own ``hooks/judge.ts``, so what is measured is what ships.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import driver
from .judgecases import Case

MARKER = "taskcut-judgebench"


def prepare(harness: Path, judge: Path, destination: Path) -> Path:
    """The harness plugin with the judge it measures copied in beside it."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(harness, destination)
    shutil.copy(judge, destination / "hooks" / "judge.ts")
    return destination


def ask(cases: list[Case], plugin: Path, scratch: Path, model: str, repeats: int, concurrency: int = 4) -> list[dict]:
    """Every case, ``repeats`` times, and what the judge answered each time."""
    scratch.mkdir(parents=True, exist_ok=True)
    request, answers = scratch / "judge-input.json", scratch / "judge-output.json"
    request.write_text(json.dumps({
        "model": model, "repeats": repeats, "concurrency": concurrency,
        "cases": [case.as_json() for case in cases],
    }))
    answers.unlink(missing_ok=True)
    environment = {k: v for k, v in os.environ.items() if k not in driver.INHERITED}
    environment["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] = "1"
    # No tools. The harness hook takes the prompt and drops it; if it fails --
    # it throws, or the engine refuses it -- the prompt goes on to the model as
    # an ordinary request, and a model with tools would set about working out
    # what "taskcut-judgebench <paths>" means, in this directory, unattended.
    subprocess.run(
        [driver._binary(), "-p", "--tools", "", "--plugin-dir", str(plugin), f"{MARKER} {request} {answers}"],
        cwd=str(scratch), env=environment, stdin=subprocess.DEVNULL, check=False, timeout=1800,
    )
    if not answers.exists():
        raise RuntimeError("the harness wrote no answers: is the plugin loading? try `claude --debug`")
    return json.loads(answers.read_text())


@dataclass
class Scored:
    id: str
    group: str
    expect: str
    verdicts: list[str]

    @property
    def right(self) -> int:
        return sum(v == self.expect for v in self.verdicts)


def score(cases: list[Case], answers: list[dict]) -> list[Scored]:
    verdicts: dict[str, list[str]] = defaultdict(list)
    for answer in sorted(answers, key=lambda a: (a["id"], a["run"])):
        verdicts[answer["id"]].append(answer["verdict"])
    return [Scored(case.id, case.group, case.expect, verdicts[case.id]) for case in cases]


def summary(scored: list[Scored]) -> list[str]:
    """One line per group, then every case the judge got wrong at least once."""
    groups: dict[str, list[Scored]] = defaultdict(list)
    for s in scored:
        groups[s.group].append(s)
    lines = []
    for group, members in groups.items():
        right = sum(s.right for s in members)
        asked = sum(len(s.verdicts) for s in members)
        lines.append(f"  {group:<34} {right:>3}/{asked:<3}")
    right, asked = sum(s.right for s in scored), sum(len(s.verdicts) for s in scored)
    lines.append(f"  {'all':<34} {right:>3}/{asked:<3}")
    for s in scored:
        if s.right < len(s.verdicts):
            lines.append(f"  wrong: {s.id} expected {s.expect}, got {', '.join(s.verdicts)}")
    return lines
