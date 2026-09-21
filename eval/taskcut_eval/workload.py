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


#: A fact the work established and then replaced. Only the replacement is
#: correct, and an answer that still offers the original is wrong however
#: confidently it also mentions the new one.
KIND_SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Probe:
    """One question asked after the work, with the strings a correct answer contains."""

    id: str
    kind: str
    question: str
    expect: tuple[str, ...]
    #: Strings whose presence makes the answer wrong whatever else it contains.
    #: Without this a superseded value cannot be graded: an answer naming both
    #: the old value and the new one matches every expectation and is useless.
    reject: tuple[str, ...] = ()

    def grade(self, answer: str) -> tuple[int, int]:
        """Returns (matched, expected). Case-insensitive substring matching keeps
        the grader out of the business of judging prose: every expectation is a
        literal that a correct answer has to contain."""
        low = answer.lower()
        return sum(1 for e in self.expect if e.lower() in low), len(self.expect)

    def rejected(self, answer: str) -> list[str]:
        low = answer.lower()
        return [r for r in self.reject if r.lower() in low]


@dataclass(frozen=True)
class Check:
    """A shell assertion run against the finished workspace.

    A probe asks the model what it knows. A check asks the work whether it
    holds together, which is the only honest grade for a task that produced
    something. Exit status zero passes. It runs with the workspace as the
    working directory, after the session has ended and before anything else
    touches it.
    """

    id: str
    description: str
    command: str
    #: What a failure means. A check that fails because the model never got
    #: that far is a different finding from one that fails because the model
    #: contradicted a decision it had made earlier, and the report says which.
    kind: str = "consistency"


@dataclass(frozen=True)
class Constraint:
    """A rule set in the opening turn that every step's answer has to satisfy.

    Probes ask what the model remembers once the work is over. A constraint is
    checked against the work itself, step by step, which is where a rule set at
    the start is actually forgotten.
    """

    id: str
    description: str
    #: A regular expression the step's answer must match.
    pattern: str


@dataclass(frozen=True)
class Source:
    """Where the workspace comes from."""

    kind: str  # 'git' | 'generated'
    url: str = ""
    ref: str = ""
    generator: str = ""
    #: Run after a clone, with the workspace as its argument. A workload built
    #: on a real repository usually needs one: an environment to run the tests
    #: in, and whatever it does to the checkout to create the work.
    prepare: str = ""


@dataclass(frozen=True)
class Workload:
    name: str
    description: str
    source: Source
    files: tuple[str, ...]
    step_template: str
    probes: tuple[Probe, ...]
    #: Sent as its own turn before any step, when the workload has one. It is
    #: the standing task, and it is the turn taskcut always keeps.
    briefing: str = ""
    constraints: tuple[Constraint, ...] = ()
    checks: tuple[Check, ...] = ()
    #: Files the generator lays down that the steps do not name -- a test
    #: suite, a fixture -- so `materialise` can verify they arrived.
    fixtures: tuple[str, ...] = ()

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
            prepare=src.get("prepare", ""),
        ),
        files=tuple(raw["files"]),
        step_template=raw["step_template"],
        probes=tuple(
            Probe(
                id=p["id"],
                kind=p["kind"],
                question=p["question"],
                expect=tuple(p["expect"]),
                reject=tuple(p.get("reject", ())),
            )
            for p in raw["probes"]
        ),
        briefing=raw.get("briefing", ""),
        constraints=tuple(
            Constraint(id=c["id"], description=c["description"], pattern=c["pattern"])
            for c in raw.get("constraints", ())
        ),
        checks=tuple(
            Check(id=c["id"], description=c["description"], command=c["command"], kind=c.get("kind", "consistency"))
            for c in raw.get("checks", ())
        ),
        fixtures=tuple(raw.get("fixtures", ())),
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
            if workload.source.ref:
                # Pinned: fetch exactly that commit and nothing else. A shallow
                # clone of the default branch would move under the benchmark as
                # upstream moves, and the same workload would stop being the
                # same work.
                subprocess.run(["git", "init", "--quiet", str(root)], check=True)
                subprocess.run(["git", "-C", str(root), "remote", "add", "origin", workload.source.url], check=True)
                subprocess.run(
                    ["git", "-C", str(root), "fetch", "--quiet", "--depth", "1", "origin", workload.source.ref],
                    check=True,
                )
                subprocess.run(["git", "-C", str(root), "checkout", "--quiet", "FETCH_HEAD"], check=True)
            else:
                subprocess.run(
                    ["git", "clone", "--quiet", "--depth", "1", workload.source.url, str(root)],
                    check=True,
                )
        if workload.source.prepare:
            # "script.py arg ..." -- the arguments let one prepare script serve
            # several workloads rather than being copied for each.
            name, *extra = workload.source.prepare.split()
            script = generators / name
            if not script.exists():
                raise FileNotFoundError(f"prepare script not found: {script}")
            subprocess.run(["python3", str(script), str(root), *extra], check=True)
    elif workload.source.kind == "generated":
        script = generators / workload.source.generator
        if not script.exists():
            raise FileNotFoundError(f"generator not found: {script}")
        subprocess.run(["python3", str(script), str(root)], check=True)
    else:
        raise ValueError(f"unknown source kind: {workload.source.kind}")

    # A workload whose steps create the files cannot require them up front.
    required = workload.fixtures if workload.checks else workload.files
    missing = [f for f in required if not (root / f).exists()]
    if missing:
        raise FileNotFoundError(f"{workload.name}: workspace is missing {missing}")
    return root


def check_ground_truth(workload: Workload, root: Path) -> list[str]:
    """Every expectation must actually appear somewhere in the workload's files.

    A probe whose answer is not in the material grades every arm as wrong and
    silently removes itself from the comparison, so this runs before a workload
    is ever used.
    """
    # A workload that builds its own material has nothing to check against yet:
    # its files, and every answer about them, come into existence during the
    # session. Such a workload is graded by its checks, which run afterwards.
    if workload.checks:
        return []
    present = [root / f for f in workload.files if (root / f).exists()]
    haystack = "\n".join(p.read_text(errors="replace") for p in present).lower()
    problems = []
    for probe in workload.probes:
        for expectation in probe.expect:
            if expectation.lower() not in haystack:
                problems.append(f"{workload.name}/{probe.id}: {expectation!r} is not in the source files")
        for rejected in probe.reject:
            # A rejected string has to be in the material too. If it is not
            # there, nothing could have produced it and the probe proves nothing.
            if rejected.lower() not in haystack:
                problems.append(f"{workload.name}/{probe.id}: rejects {rejected!r}, which is not in the source files")
        if set(probe.expect) & set(probe.reject):
            problems.append(f"{workload.name}/{probe.id}: expects and rejects the same string")
    return problems
