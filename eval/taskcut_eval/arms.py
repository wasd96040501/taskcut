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
    #: Overrides written into the plugin manifest's userConfig defaults. The
    #: harness loads taskcut with --plugin-dir, which takes no --config, so a
    #: setting has to be changed in a copy of the manifest.
    config: Mapping[str, object] = field(default_factory=dict)
    #: Whether the step prompts should ask the model to close each sub-task.
    #: A session without the plugin has no such tool, and telling it to call one
    #: measures its confusion rather than its context.
    closes_tasks: bool = False


#: The floor exists to keep taskcut off short runs. A benchmark that respects it
#: measures nothing, so every cutting arm forces it to zero and the cost of doing
#: so is reported rather than hidden.
_FORCE_EVERY_BOUNDARY = {"floorPercent": 0, "activation": "always"}


ARMS: dict[str, Arm] = {
    "off": Arm(
        name="off",
        description="Baseline. The plugin is loaded but switched off, so the transcript grows as usual.",
        env={"TASKCUT": "0"},
        config=_FORCE_EVERY_BOUNDARY,
        closes_tasks=False,
    ),
    "boundary": Arm(
        name="boundary",
        description="taskcut as shipped: the conclusion the model writes at close_task is all that survives.",
        env={"TASKCUT": "1"},
        config=_FORCE_EVERY_BOUNDARY,
        closes_tasks=True,
    ),
    "directed": Arm(
        name="directed",
        description="The conclusion is written instead by a small model reading the dropped work, aimed at the standing task.",
        env={"TASKCUT": "1"},
        config={**_FORCE_EVERY_BOUNDARY, "ledgerMode": "directed"},
        closes_tasks=True,
    ),
}


def get(name: str) -> Arm:
    try:
        return ARMS[name]
    except KeyError:
        raise SystemExit(f"unknown arm {name!r}; known arms: {', '.join(sorted(ARMS))}") from None
