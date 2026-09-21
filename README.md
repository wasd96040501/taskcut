# taskcut

[![CI](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml/badge.svg)](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin that compacts the
conversation when a sub-task ends, instead of when the context window fills.

```
              before                                  after
  ────────────────────────────────      ────────────────────────────────
  you:       "do sub-task A"            you:       "do sub-task A"
  assistant: reads 9 files              you:       "do sub-task C"
  you:        tool results              you:       [ledger]
  assistant: runs 4 commands                       1. [CLOSED] sub-task A
  you:        tool results                            <what it established>
  assistant: two dead ends                         2. [CLOSED] sub-task B
  you:       "do sub-task B"                          <what it established>
  assistant: reads 6 more files
  ...  ~40 more messages  ...
  you:       "do sub-task C"
```

Your own turns are kept **word for word**. Everything the model did for a
finished sub-task is replaced by the conclusion the model itself wrote. No
summariser runs, so nothing that is kept is paraphrased.

## Try it in two minutes

Needs Claude Code **2.1.278 or newer** (`claude --version`).

```bash
mkdir taskcut-trial && cd taskcut-trial && git init -q
printf 'alpha\nbeta\ngamma\n' > a.txt
printf 'delta\nepsilon\n'     > b.txt

claude plugin marketplace add wasd96040501/taskcut --scope project
claude plugin install taskcut@taskcut --scope project --config floorPercent=0

CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude
```

Answer **yes** to the folder-trust prompt, then paste these three, one at a time:

```
Sub-task 1: run `wc -l a.txt` and tell me the number. Then call close_task.
```
```
Sub-task 2: run `cat b.txt` and tell me the last word. Then call close_task.
```
```
Without running any tool: list every sub-task you have closed.
```

The third answer comes back complete — both sub-tasks, with what each
established — even though the work that produced them is no longer in the
conversation. Watch `ctx N%` in the status line: it does not climb.

Throw the trial away with `cd .. && rm -rf taskcut-trial`.

> `floorPercent=0` is for the demo only. It makes taskcut cut at **every**
> boundary so you can see it work. The default is `40`, which is the setting
> you actually want — see [What it costs](#what-it-costs).

## The problem it solves

Claude Code compacts when the window fills. On a job that runs for hours or
days, that moment almost never lines up with the shape of the work: it fires in
the middle of a sub-task, summarising away detail that is still live while
keeping detail from work that finished an hour ago.

A long job is a sequence of shorter ones, and the moment when *what still
matters* has a clean answer is the end of a sub-task. taskcut gives the model a
tool, `close_task`, and cuts there instead.

## Install it for real

Pick where it should run. That is the only decision.

```bash
# this repository, for everyone who clones it
claude plugin marketplace add wasd96040501/taskcut --scope project
claude plugin install taskcut@taskcut --scope project

# this repository, for you alone (not committed)
claude plugin marketplace add wasd96040501/taskcut --scope local
claude plugin install taskcut@taskcut --scope local

# every session on this machine
claude plugin marketplace add wasd96040501/taskcut
claude plugin install taskcut@taskcut --scope user
```

Then start a session with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`, and ask
for `close_task` when a piece of work is done — in the prompt, or once in the
project's `CLAUDE.md`:

```markdown
Call close_task when you finish a sub-task and move on to the next.
```

**Switching it off for one session:** `TASKCUT=0 claude`. That outranks
everything.

**Removing it:**

```bash
claude plugin uninstall taskcut@taskcut
claude plugin marketplace remove taskcut
```

## What it costs

Measured against the same work with the plugin off, over five workloads
including two that build something and are graded by running it
([docs/measurement.md](docs/measurement.md)):

| | what was measured |
| --- | --- |
| **Context stops climbing** | ten sub-tasks ended at 44,743 tokens of context instead of 107,857 — **59% less**, every probe still answered, without going back to disk once |
| **How much less varies** | the same ten sub-tasks against real framework source saved **10%**, because a real module needs far more said about it and the ledger grew accordingly |
| **Accuracy never moved** | across sixteen runs, no arm ever answered wrongly or failed an acceptance check. What a cut costs is re-reading, not correctness |
| **A cut is not free** | with the floor forced to zero, **$0.41 to $2.04** more per run, 1.4× to 2.7× — which is exactly what the floor exists to avoid |
| **Still unproven** | nothing yet shows the *baseline* doing worse work. taskcut reliably does what it says to the context; whether that buys anything is open. [What would settle it](docs/measurement.md#6-what-has-not-been-shown) |
| **On a 1M window it waits a long time** | twenty real changes to click — bugs and features, forty minutes of work in one session — peaked at 294,690 tokens, 29% of Sonnet 5's window, with every change correct. At the default floor of 40% taskcut does not act until 400,000. It is for sessions that genuinely get that long |
| **Closing a task costs a round-trip** | each `close_task` is one more request, which re-reads the context from the cache: **about +10%** over those twenty changes ($11.50 against $10.37), paid whether or not anything is cut |

One run per cell, on Sonnet. These show the shape of a difference, not its size.

## Settings

Every setting has a working default. Set one at install time with
`--config KEY=VALUE`, repeatable, or change it later from a session with
`/plugin`.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `40` | Context fill, as a percentage, below which a closed sub-task is recorded but no cut is made. A cut re-caches the kept set at full price, measured at 12k–15k tokens, so below the floor it costs more than it saves. `0` cuts at every boundary. |
| `recentHumanTurns` | `2` | How many of your most recent turns are kept beside the first one. Your turns are unbounded on a long run, so keeping all of them only moves the growth. |
| `ledgerVerbatim` | `12` | How many closed sub-tasks stay in the model's own words. Past this, the oldest fold into one rolled-up entry. |
| `foldModel` | `haiku` | The model that folds them. An alias or a full id, resolved the way a `--model` value is. |
| `ledgerMode` | `outcome` | Who writes a ledger entry. `directed` hands the job to `foldModel`; measured, it halves the ledger and doubles the re-reading, so it is off by default. |

## How it works

At `session.start` taskcut registers one tool, `close_task`. Its argument is the
conclusion, and it is the only thing that survives. When the model calls it,
the conclusion goes into a session-keyed ledger. At the end of that turn, if the
window has filled past `floorPercent`, a `session.compact` hook answers with a
transcript it builds itself:

* your first turn, and your most recent `recentHumanTurns`, **verbatim** by
  their engine handles — nothing you said is ever paraphrased. The first is
  always kept because nothing else records what the job is for;
* one message holding the ledger of closed sub-tasks.

That hook never calls `next`, so no summariser runs and the cut is a
deterministic function of the transcript.

| File | Role |
| --- | --- |
| `hooks/register.ts` | Every hook, and every call on the engine interface. |
| `hooks/ledger.ts` | The ledger and the keep-set rule, as pure functions. |
| `hooks/activation.ts` | Whether taskcut runs at all, as a pure rule. |
| `hooks/config.ts` | Settings, with defaults for anything unset. |
| `eval/` | The benchmark. `make eval-list`. |

The split is not stylistic. A hooks module may pass `$` only to a function
declared in the same file; the loader refuses a module that passes it across an
import. So everything that touches the engine lives in `register.ts`, and
everything that can be reasoned about as plain data lives beside it.

## Limitations

* **Interactive sessions only.** `claude -p` and the SDK transport cannot
  compact at all, so taskcut logs and does nothing there. A terminal session or
  `claude --bg` works.
* **The conclusion is only as good as what the model wrote.** taskcut keeps the
  `outcome` text exactly; it does not check that it is sufficient.
* **No assistant message survives a cut.** After a cut the model cannot see what
  it said in the turn that just ended, so a follow-up phrased as *the approach
  you just described* has nothing to resolve against. On a long autonomous run
  this is the point; in a conversation it is a cost.
* **Every boundary costs a round-trip.** Calling `close_task` ends the model's
  response, so finishing the turn takes one more request that re-reads the
  context from the cache — about 10% over a twenty-change session, whether or
  not anything is cut. After a cut the model also reloads the tool's schema
  with a `ToolSearch` call.
* **One session per process.** Module state assumes Claude Code loads a hooks
  module once per session, which holds today but the API does not guarantee.
* **Early access.** The function-hooks API may change between Claude Code
  releases. `./scripts/validate.sh` reports anything the engine would refuse
  before a session loads the plugin.

## Documentation

* [docs/measurement.md](docs/measurement.md) — what the benchmark found: what a
  cut costs, what it keeps, and what has not been shown.
* [eval/README.md](eval/README.md) — the benchmark itself.
* [docs/design.md](docs/design.md) — why the cut is shaped this way, and the
  constraints that produced each rule.
* [docs/troubleshooting.md](docs/troubleshooting.md) — what to check when
  nothing is being compacted.
* [docs/compatibility.md](docs/compatibility.md) — what a Claude Code upgrade
  can break.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). `make check` runs everything CI runs.

## License

Apache License 2.0. See [LICENSE](LICENSE).
