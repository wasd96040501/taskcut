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
finished sub-task is replaced by the answer it gave for it. No summariser runs,
so nothing that is kept is paraphrased. And until the context is actually
filling up, taskcut does nothing at all and costs nothing.

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
Run `wc -l a.txt` and tell me the number.
```
```
Run `cat b.txt` and tell me the last word.
```
```
Without running any tool: list every task I have given you, with its result.
```

After each of the first two, a dim line says what taskcut decided:
`taskcut: context at 3%, the work is finished; dropping its working context`.
The third answer comes back complete — both tasks, with their results — even
though the work that produced them is no longer in the conversation. Nothing
in the prompts mentions taskcut: it needs nothing from you or from the model.

Throw the trial away with `cd .. && rm -rf taskcut-trial`.

> `floorPercent=0` is for the demo only. It makes taskcut judge **every** turn
> so you can see it work. The default is `40`, below which it does nothing —
> see [What it costs](#what-it-costs).

## The problem it solves

Claude Code compacts when the window fills. On a job that runs for hours or
days, that moment almost never lines up with the shape of the work: it fires in
the middle of a sub-task, summarising away detail that is still live while
keeping detail from work that finished an hour ago.

A long job is a sequence of shorter ones, and the moment when *what still
matters* has a clean answer is the end of a sub-task. taskcut cuts there
instead: once the context is past a floor, a small model reads what you asked
and what the assistant answered at the end of each turn, and judges whether
that piece of work is finished — the way auto mode has a classifier judge each
action.

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

Then start sessions with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`. There is
nothing to add to your prompts or to `CLAUDE.md`.

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
| `floorPercent` | `40` | Context fill, as a percentage, below which taskcut does nothing at all: no model is asked and nothing is cut. A cut re-caches the kept set at full price, measured at 12k–15k tokens, so below the floor it costs more than it saves. `0` judges every turn. |
| `recentHumanTurns` | `2` | How many of your most recent turns are kept beside the first one. Your turns are unbounded on a long run, so keeping all of them only moves the growth. |
| `ledgerVerbatim` | `12` | How many finished pieces of work stay in the model's own words. Past this, the oldest fold into one rolled-up entry. |
| `model` | `haiku` | The small model taskcut asks: whether a turn's work is finished, and to fold the ledger. An alias or a full id, resolved the way a `--model` value is. |
| `outcome` | `false` | Whether the working model is asked to write a conclusion for each sub-task. Off, its own answer is what is kept and taskcut costs it nothing. On, past the floor it is offered a `close_task` tool: that costs output tokens and one request per call, and the tool stays for the rest of the session. |

## How it works

Nothing happens until the context is past `floorPercent`. From then on, at the
end of each turn that the model finished, taskcut makes one small-model call:
it shows `model` what you asked and what the assistant answered — a few
thousand characters, never the transcript — and asks whether that work is
finished. A reply that asks you something, waits for a decision or reports
partial progress is not; the context is kept.

When it is finished, a `session.compact` hook answers with a transcript it
builds itself:

* your first turn, and your most recent `recentHumanTurns`, **verbatim** by
  their engine handles — nothing you said is ever paraphrased. The first is
  always kept because nothing else records what the job is for;
* one message holding the ledger: every request since the last cut, with the
  answer the model gave it, after the ones earlier cuts recorded.

That hook never calls `next`, so no summariser runs and the cut is a
deterministic function of the transcript. After it the context is back below
the floor, and taskcut is silent again until it fills.

| File | Role |
| --- | --- |
| `hooks/register.ts` | Every hook, and every call on the engine interface. |
| `hooks/ledger.ts` | The ledger, the keep-set rule and what the judge reads, as pure functions. |
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
* **The ledger is only as good as the answers.** taskcut keeps what the model
  answered, exactly; it does not check that it is sufficient. A model that ends
  a long job with "Done." leaves a thin record.
* **Only answers survive a cut.** The model's narration, its tool calls and
  their output go; its answer to each request stays, in the ledger. A detail it
  saw but never said has to be looked up again.
* **The judge sees the request and the answer, not the work.** It can call a
  turn finished that the model only claimed to finish. A wrong call costs
  re-reading, not a lost request: your turns and the answers survive.
* **Cuts happen between turns.** A single turn that runs for hours is not cut
  until it ends; the engine's own compaction, told what the ledger already
  settled, remains the safety net for it.
* **Under `outcome`, the tool cannot be taken back.** Claude Code has no way to
  unregister a tool, so once `close_task` has been offered it stays offered.
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
