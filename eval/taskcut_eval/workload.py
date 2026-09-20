"""What a session is asked to do, and how the answers are graded.

A workload is data. It names the files a session works through, the prompt
template applied to each, and the probes asked once the work is done. It holds
no knowledge of taskcut: the same workload runs under every arm.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

#: Placed in a probe's ``kind`` to say the fact is one the model was explicitly
#: asked for, so a conclusion written at a sub-task boundary should carry it.
KIND_HEADLINE = "headline"

#: The fact was in the material but was never asked for, so no reasonable
#: conclusion would mention it. Answering it after a cut means going back to
#: the source.
KIND_INCIDENTAL = "incidental"


@dataclass(frozen=True)
class Probe:
    """One question asked after the work, with the strings a correct answer contains."""

    id: str
    kind: str
    question: str
    expect: tuple[str, ...]

    def grade(self, answer: str) -> tuple[int, int]:
        """Returns (matched, expected). Case-insensitive substring matching keeps
        the grader out of the business of judging prose: every expectation is a
        literal that a correct answer has to contain."""
        low = answer.lower()
        return sum(1 for e in self.expect if e.lower() in low), len(self.expect)


@dataclass(frozen=True)
class Source:
    """Where the workspace comes from."""

    kind: str  # 'git' | 'generated'
    url: str = ""
    ref: str = ""
    generator: str = ""


@dataclass(frozen=True)
class Workload:
    name: str
    description: str
    source: Source
    files: tuple[str, ...]
    step_template: str
    probes: tuple[Probe, ...]

    def steps(self) -> list[str]:
        """The prompt for each sub-task, in order.

        `{file}` is the path; `{n}` is the one-based index, because a model
        tracks its own progress better when the work is numbered.
        """
        return [
            self.step_template.format(file=f, n=i, total=len(self.files))
            for i, f in enumerate(self.files, 1)
        ]


def load(path: str | Path) -> Workload:
    raw = json.loads(Path(path).read_text())
    src = raw["source"]
    return Workload(
        name=raw["name"],
        description=raw["description"],
        source=Source(
            kind=src["kind"],
            url=src.get("url", ""),
            ref=src.get("ref", ""),
            generator=src.get("generator", ""),
        ),
        files=tuple(raw["files"]),
        step_template=raw["step_template"],
        probes=tuple(
            Probe(id=p["id"], kind=p["kind"], question=p["question"], expect=tuple(p["expect"]))
            for p in raw["probes"]
        ),
    )


def load_all(directory: str | Path) -> dict[str, Workload]:
    return {w.name: w for w in (load(p) for p in sorted(Path(directory).glob("*.json")))}


def materialise(workload: Workload, root: Path, generators: Path) -> Path:
    """Puts the workload's files on disk under `root`, returning the workspace.

    A workspace is per-workload and per-arm: two arms must not share one, or the
    second session inherits the first's transcript directory and the two runs
    cannot be told apart afterwards.
    """
    root.mkdir(parents=True, exist_ok=True)
    if workload.source.kind == "git":
        if not (root / ".git").exists():
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", workload.source.url, str(root)],
                check=True,
            )
        if workload.source.ref:
            subprocess.run(["git", "-C", str(root), "checkout", "--quiet", workload.source.ref], check=True)
    elif workload.source.kind == "generated":
        script = generators / workload.source.generator
        if not script.exists():
            raise FileNotFoundError(f"generator not found: {script}")
        subprocess.run(["python3", str(script), str(root)], check=True)
    else:
        raise ValueError(f"unknown source kind: {workload.source.kind}")

    missing = [f for f in workload.files if not (root / f).exists()]
    if missing:
        raise FileNotFoundError(f"{workload.name}: workspace is missing {missing}")
    return root


def check_ground_truth(workload: Workload, root: Path) -> list[str]:
    """Every expectation must actually appear somewhere in the workload's files.

    A probe whose answer is not in the material grades every arm as wrong and
    silently removes itself from the comparison, so this runs before a workload
    is ever used.
    """
    haystack = "\n".join((root / f).read_text(errors="replace") for f in workload.files).lower()
    problems = []
    for probe in workload.probes:
        for expectation in probe.expect:
            if expectation.lower() not in haystack:
                problems.append(f"{workload.name}/{probe.id}: {expectation!r} is not in the source files")
    return problems
