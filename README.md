# taskcut

[![CI](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml/badge.svg)](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin that compacts the
conversation when a sub-task ends, instead of when the context window fills.

```
  without taskcut                          with taskcut
  ───────────────────────────────────      ───────────────────────────────────
  you:  "do A"   ... A's work ...          you:  "do A"   ... A's work ...
  you:  "do B"   ... B's work ...                         A is done
  you:  "do C"   ... C's work, half-way                   ── compacted ──
                 ── window full ──         you:  "do B"   ... B's work ...
                 ── compacted ──                          B is done
                 C's live detail                          ── compacted ──
                 summarised away           you:  "do C"   ... C's work ...
```

taskcut changes **when** Claude Code compacts, not how. Once the context is
past a floor, a small model judges at the end of each turn whether the work
you asked for is finished — reading what auto mode's permission classifier
reads. If it is, taskcut runs Claude Code's own compaction, the one `/compact`
runs. Below the floor it does nothing at all and costs nothing, and nothing in
your prompts has to mention it.

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

The install may note that some options are not yet set. That is fine: every
setting has a default.

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

After each of the first two, a dim line says what taskcut decided —
`taskcut: context at 4%, the work is finished; compacting` — and Claude Code
compacts, as `/compact` would. The third answer comes back complete, both tasks
with their results, from the compacted conversation. Nothing in the prompts
mentions taskcut: it needs nothing from you or from the model.

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
matters* has a clean answer is the end of a sub-task. taskcut compacts there
instead, and leaves what a compaction keeps to Claude Code.

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

| | |
| --- | --- |
| **Below the floor** | Nothing. No model is asked, nothing is written, and the working model is never told taskcut exists. `make eval-mechanism` asserts it on a real session. |
| **Each finished turn past the floor** | One call to `model` — `haiku` by default — reading at most about 12k tokens: your messages, the assistant's non-read-only tool calls, `CLAUDE.md` and the reply. Under two cents. |
| **Each compaction** | Exactly what `/compact` costs, because it is `/compact`. On a 65k-token session it took 21–25 seconds; at 315k, 80 seconds. |
| **On real work** | Twenty real changes to click in one Sonnet 5 session, floor 30%: for nineteen, taskcut did nothing at all. After the nineteenth it judged the turn finished and compacted 315,608 tokens to a 5,960-token summary; the twentieth ran on 37,646 and passed. Both arms passed all 22 checks. |

What it buys is the question the benchmark is for; see
[docs/measurement.md](docs/measurement.md), which also records what earlier
versions — which built their own compacted transcript — measured.

On a 1M window the default floor of 40% is 400,000 tokens, and twenty real
changes in one Sonnet 5 session reached 29%. taskcut is for sessions that
genuinely get that long.

## Settings

Both have a working default. Set one at install time with `--config KEY=VALUE`,
or change it later from a session with `/plugin`.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `40` | Context fill, as a percentage, below which taskcut does nothing at all: no model is asked and nothing is compacted. A compaction invalidates the prompt cache, so below the floor it costs more than it saves. `0` judges every turn. |
| `model` | `haiku` | The model that judges whether a turn's work is finished. An alias or a full id, resolved the way a `--model` value is. |

## How it works

Nothing happens until the context is past `floorPercent`, read from the same
figure the status line shows. From then on, at the end of each turn the model
finished, taskcut makes one call to `model` with `$.model.classify`, the hooks
API's classifier. It sees what auto mode's permission classifier sees — every
message you sent, every tool call the assistant made except read-only lookups,
and `CLAUDE.md`, with all tool output stripped — plus the reply the assistant
just stopped on, and it answers `finished` or `unfinished`.

A reply that asks you something, waits for a decision or reports partial
progress is `unfinished`, and nothing happens. On `finished`, taskcut calls
`$.session.compact()` — the same call `/compact` makes — and Claude Code
compacts as it always does. The context drops back below the floor, and taskcut
is silent again until it fills.

| File | Role |
| --- | --- |
| `hooks/register.ts` | The two hooks, and every call on the engine interface. |
| `hooks/judge.ts` | What the judge reads, as a pure function. |
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
* **The judge sees what was done, not what came of it.** Like the permission
  classifier, it never reads tool output, so it can call a turn finished that
  the model only claimed to finish. A wrong call costs a compaction a turn
  early, which is what Claude Code would have done at the threshold anyway.
* **Compaction happens between turns.** A single turn that runs for hours is
  not compacted until it ends; Claude Code's own threshold compaction remains
  the safety net inside it.
* **A prompt typed while the judge runs wins.** Compaction cannot start once the
  next turn has, so it is skipped and noted; the next finished turn is judged
  again.
* **One session per process.** Module state assumes Claude Code loads a hooks
  module once per session, which holds today but the API does not guarantee.
* **Early access.** The function-hooks API may change between Claude Code
  releases. `./scripts/validate.sh` reports anything the engine would refuse
  before a session loads the plugin.

## Documentation

* [docs/measurement.md](docs/measurement.md) — what the benchmark found, for
  this version and the ones before it.
* [eval/README.md](eval/README.md) — the benchmark itself.
* [docs/design.md](docs/design.md) — why taskcut decides only when, and the
  designs it replaced.
* [docs/troubleshooting.md](docs/troubleshooting.md) — what to check when
  nothing is being compacted.
* [docs/compatibility.md](docs/compatibility.md) — what a Claude Code upgrade
  can break.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). `make check` runs everything CI runs.

## License

Apache License 2.0. See [LICENSE](LICENSE).
