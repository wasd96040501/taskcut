"""How taskcut is configured for a run.

An arm is the independent variable. It carries the environment and the plugin
settings for one session and nothing else: it names no workload, and no metric
reads it. Adding an arm is adding an entry here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class Arm:
    name: str
    description: str
    #: Extra environment for the session. `TASKCUT` is the plugin's own switch.
    env: Mapping[str, str] = field(default_factory=dict)
    #: Whether a sweep runs this arm. An arm whose question has been answered
    #: stays here so the result can be reproduced, but costs nothing to leave in.
    default: bool = True
    #: Overrides written into the plugin manifest's userConfig defaults. The
    #: harness loads taskcut with --plugin-dir, which takes no --config, so a
    #: setting has to be changed in a copy of the manifest.
    config: Mapping[str, object] = field(default_factory=dict)
    #: Whether the step prompts should ask the model to close each sub-task.
    #: A session without the plugin has no such tool, and telling it to call one
    #: measures its confusion rather than its context.
    closes_tasks: bool = False


#: The floor a cutting arm runs at. Zero would cut at every boundary and make
#: the mechanism easy to see, but it is not a setting anyone would use and it
#: measures taskcut at its most expensive. Thirty is a figure a real session
#: reaches, and it is below the shipped default of forty, so a benchmark run
#: reaches it without being contrived.
_REALISTIC_FLOOR = {"floorPercent": 30}


ARMS: dict[str, Arm] = {
    "off": Arm(
        name="off",
        description="Baseline. The plugin is loaded but switched off, so the transcript grows as usual.",
        env={"TASKCUT": "0"},
        config=_REALISTIC_FLOOR,
        closes_tasks=False,
    ),
    "boundary": Arm(
        name="boundary",
        description="taskcut as shipped: the conclusion the model writes at close_task is all that survives.",
        env={"TASKCUT": "1"},
        config=_REALISTIC_FLOOR,
        closes_tasks=True,
    ),
    "directed": Arm(
        name="directed",
        description=(
            "Falsified, kept for reproduction: the conclusion is written by a small model reading "
            "the dropped work. It halves the ledger and doubles the re-reading. Not in the default sweep."
        ),
        env={"TASKCUT": "1"},
        config={**_REALISTIC_FLOOR, "ledgerMode": "directed"},
        closes_tasks=True,
        default=False,
    ),
}


def sweep() -> list[Arm]:
    """The arms a comparison runs unless one is named. An arm drops out of this
    when its question has been settled; it stays in ARMS so the run that settled
    it can be repeated."""
    return [arm for arm in ARMS.values() if arm.default]


def get(name: str) -> Arm:
    try:
        return ARMS[name]
    except KeyError:
        raise SystemExit(f"unknown arm {name!r}; known arms: {', '.join(sorted(ARMS))}") from None
