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

(A note that options are not yet set is fine: every setting has a default.)

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

Pick where it should run:

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

Then start sessions with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`. Nothing
goes in your prompts or `CLAUDE.md`.

On a 1M-token window the default floor of 40% is 400,000 tokens, which only a
long session reaches. To watch it act on ordinary work first, install with
`--config floorPercent=10`.

Off for one session: `TASKCUT=0 claude`. Removing it:
`claude plugin uninstall taskcut@taskcut && claude plugin marketplace remove taskcut`.

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
or change it later from a session with `/plugin`.

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
