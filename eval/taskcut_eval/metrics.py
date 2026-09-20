"""Numbers derived from a transcript. Every function here is pure.

Three questions are asked of a run, and they are not the same question:

    cost            what the session spent
    context health  how much it was carrying while it worked
    fidelity        whether it could still answer afterwards, and at what price

taskcut can win one and lose another, so they are reported side by side and
never collapsed into a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from .transcript import Transcript, Turn
from .workload import Constraint, Probe, Workload

#: Published cache multipliers, in base-input-token equivalents. A cache write
#: costs about 1.25 of a base input token and a cache read about 0.1, so adding
#: the three input counters together overstates a long session several times
#: over. Every cost here is weighted.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


@dataclass(frozen=True)
class Cost:
    requests: int
    read: int
    write: int
    plain: int
    output: int

    @property
    def weighted(self) -> float:
        """Input cost in base-input-token equivalents."""
        return self.plain + CACHE_WRITE_MULTIPLIER * self.write + CACHE_READ_MULTIPLIER * self.read

    @property
    def naive(self) -> int:
        """The sum people usually quote. Kept only to show how wrong it is."""
        return self.plain + self.write + self.read


def cost(transcript: Transcript) -> Cost:
    requests = transcript.requests
    return Cost(
        requests=len(requests),
        read=sum(r.read for r in requests),
        write=sum(r.write for r in requests),
        plain=sum(r.plain for r in requests),
        output=sum(r.output for r in requests),
    )


def prefix_series(transcript: Transcript) -> list[int]:
    """What the model carried into each turn, turn by turn.

    The first request of a turn sends the whole conversation so far, so its
    input is the size of the context the model is working in. It has to be read
    plus write, not read alone: a cut invalidates the cache past the tool
    definitions, so most of what an arm that cuts carries arrives as a cache
    write. Counting only the read makes a cutting arm look emptier than it is.
    """
    return [turn.requests[0].read + turn.requests[0].write for turn in transcript.turns if turn.requests]


#: Characters per token, near enough for a ratio. The exact figure varies with
#: the text; nothing here turns on the third digit.
CHARS_PER_TOKEN = 4


def ledger_tokens(transcript: Transcript) -> int:
    """How big the ledger had grown by the end, in tokens.

    This is the variable that decides whether a cut is worth anything. A cut
    replaces the working context with the ledger, so the saving is the
    difference between them: a ledger that approaches the size of the material
    it stands for saves nothing, however faithfully it was written.
    """
    return len(transcript.ledgers[-1]) // CHARS_PER_TOKEN if transcript.ledgers else 0


@dataclass(frozen=True)
class ProbeResult:
    id: str
    kind: str
    matched: int
    expected: int
    tools: int
    answer: str
    #: Strings the probe rejects that the answer contained. A superseded value
    #: offered as current is wrong even when the current one is named too.
    rejected: tuple[str, ...] = ()

    @property
    def correct(self) -> bool:
        return self.expected > 0 and self.matched == self.expected and not self.rejected

    @property
    def went_to_disk(self) -> bool:
        """The model could not answer from context and had to go back to the source."""
        return self.tools > 0


def probe_results(transcript: Transcript, workload: Workload) -> list[ProbeResult]:
    out = []
    for probe in workload.probes:
        turn = transcript.turn_for(probe.question)
        if turn is None:
            out.append(ProbeResult(probe.id, probe.kind, 0, len(probe.expect), 0, "(not asked)"))
            continue
        matched, expected = probe.grade(turn.answer)
        out.append(
            ProbeResult(
                probe.id, probe.kind, matched, expected, len(turn.tools), turn.answer,
                tuple(probe.rejected(turn.answer)),
            )
        )
    return out


@dataclass(frozen=True)
class Drift:
    """Whether a rule set in the opening turn was still being applied by the end.

    A probe asks what the model remembers once the work is over, which is the
    easiest thing for it to do. A constraint is checked against each step of the
    work as it happened, which is where a rule set at the start is actually
    dropped. The series is per step, in order: the shape is the finding, not the
    total.
    """

    id: str
    description: str
    per_step: tuple[bool, ...]

    @property
    def held(self) -> int:
        return sum(self.per_step)

    @property
    def steps(self) -> int:
        return len(self.per_step)

    @property
    def first_lapse(self) -> int | None:
        """The one-based step where the rule was first not applied."""
        for index, ok in enumerate(self.per_step, 1):
            if not ok:
                return index
        return None


def constraint_drift(transcript: Transcript, workload: Workload) -> list[Drift]:
    steps = workload.steps()
    answers = []
    for step in steps:
        # An arm may append its own clause to a step, so match on the step text.
        candidates = [t for t in transcript.turns if t.prompt.strip().startswith(step.strip()[:60])]
        live = [t for t in candidates if t.requests] or candidates
        answers.append(live[-1].answer if live else "")
    out = []
    for constraint in workload.constraints:
        expression = re.compile(constraint.pattern, re.IGNORECASE)
        out.append(
            Drift(
                id=constraint.id,
                description=constraint.description,
                per_step=tuple(bool(expression.search(a)) for a in answers),
            )
        )
    return out


@dataclass(frozen=True)
class Fidelity:
    kind: str
    asked: int
    correct: int
    to_disk: int
    tool_calls: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.asked if self.asked else 0.0

    @property
    def reread_rate(self) -> float:
        return self.to_disk / self.asked if self.asked else 0.0


def fidelity(results: list[ProbeResult]) -> dict[str, Fidelity]:
    """Accuracy and re-read rate, split by whether the fact was ever asked for.

    Splitting matters. A conclusion written at a boundary carries the headline
    fact by construction, so an arm that cuts should hold accuracy there for
    free. The incidental facts are the ones a cut actually throws away, and the
    honest question is what recovering them costs.
    """
    out: dict[str, Fidelity] = {}
    for kind in sorted({r.kind for r in results}):
        group = [r for r in results if r.kind == kind]
        out[kind] = Fidelity(
            kind=kind,
            asked=len(group),
            correct=sum(1 for r in group if r.correct),
            to_disk=sum(1 for r in group if r.went_to_disk),
            tool_calls=sum(r.tools for r in group),
        )
    return out


@dataclass(frozen=True)
class Run:
    """Everything one workload-and-arm pair produced."""

    workload: str
    arm: str
    cost: Cost
    prefix: list[int]
    probes: list[ProbeResult]
    #: Tokens the ledger had grown to by the end; zero for an arm that never cut.
    ledger: int
    #: Ledger messages recorded, an upper bound on the number of cuts.
    ledger_messages: int
    drift: list[Drift]
    #: Filled in from the sidecar a run writes; empty for a workload with none.
    checks: list = field(default_factory=list)

    @property
    def fidelity(self) -> dict[str, Fidelity]:
        return fidelity(self.probes)

    @property
    def peak_context(self) -> int:
        return max(self.prefix) if self.prefix else 0

    @property
    def mean_context(self) -> float:
        return mean(self.prefix) if self.prefix else 0.0


def summarise(transcript: Transcript, workload: Workload, arm: str) -> Run:
    return Run(
        workload=workload.name,
        arm=arm,
        cost=cost(transcript),
        prefix=prefix_series(transcript),
        probes=probe_results(transcript, workload),
        ledger=ledger_tokens(transcript),
        ledger_messages=transcript.ledger_messages,
        drift=constraint_drift(transcript, workload),
    )


@dataclass(frozen=True)
class CheckResult:
    id: str
    description: str
    kind: str
    passed: bool
    detail: str


def run_checks(workload: Workload, workspace) -> list[CheckResult]:
    """Runs each check in the finished workspace.

    This is not pure, and it is the only thing here that is not: a check has to
    execute the work to find out whether it holds together. It runs once, right
    after the session, and its verdicts are stored beside the transcript so
    every later report is reading a record rather than re-running anything.
    """
    import subprocess

    out = []
    for check in workload.checks:
        try:
            done = subprocess.run(
                check.command, shell=True, cwd=str(workspace),
                capture_output=True, text=True, timeout=300,
            )
            passed = done.returncode == 0
            detail = (done.stdout + done.stderr).strip()[-400:]
        except subprocess.TimeoutExpired:
            passed, detail = False, "timed out after 300s"
        out.append(CheckResult(check.id, check.description, check.kind, passed, detail))
    return out
