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

## Try it

Needs Claude Code **2.1.278 or newer**. In a project you work on — installed for
you alone, nothing committed:

```bash
claude plugin marketplace add wasd96040501/taskcut --scope local
claude plugin install taskcut@taskcut --scope local
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude
```

The install notes that options are "not yet set". That is fine: unset, each
takes its default.

Then work as usual. Nothing happens until the context passes 40% — the `ctx`
figure in the status line. From then on, each turn that finishes a piece of
work ends with a dim line, and Claude Code compacts exactly as `/compact` would:

```
taskcut: context at 43%, the work is finished; compacting
```

A turn that ends in a question, or with the work half done, is left alone:
`the work is not finished; keeping it`. Nothing you type mentions taskcut.

To remove it:

```bash
claude plugin uninstall taskcut@taskcut --scope local
claude plugin marketplace remove taskcut --scope local
```

## The problem it solves

Claude Code compacts when the window fills. On a job that runs for hours or
days, that moment almost never lines up with the shape of the work: it fires in
the middle of a sub-task, summarising away detail that is still live while
keeping detail from work that finished an hour ago.

A long job is a sequence of shorter ones, and the moment when *what still
matters* has a clean answer is the end of a sub-task. taskcut compacts there
instead, and leaves what a compaction keeps to Claude Code.

## Install it for a whole project, or everywhere

```bash
# this repository, for everyone who clones it
claude plugin marketplace add wasd96040501/taskcut --scope project
claude plugin install taskcut@taskcut --scope project

# every session on this machine
claude plugin marketplace add wasd96040501/taskcut
claude plugin install taskcut@taskcut --scope user
```

Start sessions with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`. Off for one
session: `TASKCUT=0 claude`. To remove it, uninstall with the same `--scope`.

## What it costs

| | |
| --- | --- |
| **Below the floor** | Nothing: no model call, no tool, nothing written. |
| **Each finished turn past it** | One `haiku` call of at most ~12k tokens — about a cent. |
| **Each compaction** | Whatever `/compact` costs, because it is `/compact`. |

On twenty real changes to click in one Sonnet 5 session, with the floor at 30%,
taskcut did nothing for nineteen. After the nineteenth it judged the turn
finished and compacted 315,608 tokens to a 5,960-token summary; the twentieth
ran on 37,646 tokens and passed, as every change did with and without it.
Whether compacting earlier makes long sessions work better is what the
benchmark is for: [docs/measurement.md](docs/measurement.md).

## Settings

Both have a working default. Set one at install time with `--config KEY=VALUE`,
or change it later from a session with `/plugin`. Settings are yours, not a
scope's: Claude Code keeps plugin settings in your user settings, so they apply
wherever taskcut is installed on this machine, whatever `--scope` it was
installed with.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `40` | Context fill, as a percentage, below which taskcut does nothing at all: no model is asked and nothing is compacted. A compaction invalidates the prompt cache, so below the floor it costs more than it saves. `0` judges every turn. |
| `model` | `haiku` | The model that judges whether a turn's work is finished. An alias or a full id, resolved the way a `--model` value is. |

## How it works

At the end of each turn the model finished, taskcut reads the context fill the
status line shows. Below `floorPercent` it stops there. Past it, it asks `model`,
through the hooks API's `$.model.classify`, whether the work you asked for is
done. The judge reads what auto mode's permission classifier reads — your
messages, the assistant's tool calls except read-only lookups, and `CLAUDE.md`,
never any tool output — plus the reply it stopped on. On `finished`, taskcut
calls `$.session.compact()`, the call `/compact` makes; on anything else it
leaves the conversation alone.

The source is two files: `hooks/register.ts` (the two hooks) and
`hooks/judge.ts` (what the judge reads). [docs/design.md](docs/design.md) has
the reasoning, and the designs this one replaced.

## Limitations

* **Interactive sessions only.** `claude -p` and the SDK transport cannot
  compact; a terminal session or `claude --bg` can.
* **The judge never sees tool output**, so a reply that claims more than was
  done can fool it. The cost is a compaction a little early.
* **Compaction happens between turns.** Inside one very long turn, Claude
  Code's own threshold compaction is still the safety net.
* **A prompt typed while the judge runs wins.** The compaction is skipped and
  the next finished turn is judged again.
* **Early access.** The function-hooks API may change between Claude Code
  releases; `make validate` reports anything the engine would refuse.

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
