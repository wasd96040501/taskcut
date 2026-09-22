# taskcut

[![CI](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml/badge.svg)](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

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
past a floor, a model judges each step Claude takes — and the reply a turn ends
on — for whether it just finished a piece of the work, reading what auto mode's
permission classifier reads. If it did, taskcut runs Claude Code's own
compaction, the one `/compact` runs. That works inside one long turn too: hand
over twenty tasks in one message and walk away, and it compacts between them.
Below the floor it does nothing at all and costs nothing, and nothing in your
prompts has to mention it.

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

`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` is needed on every launch while function
hooks are in early access. Without it the plugin is listed as installed but never
runs, and nothing says so. To set it once, put
`"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"` under `env` in
`~/.claude/settings.json`. To check that taskcut loads:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude -p ok --debug-file /tmp/taskcut.log >/dev/null
grep 'taskcut@taskcut loaded' /tmp/taskcut.log
```

Then work as usual. Nothing happens until the context passes 35% — the `ctx`
figure in the status line. From then on, when a piece of work is finished, a
dim line says so and Claude Code compacts exactly as `/compact` would:

```
taskcut: context at 43%, the work is finished; compacting
```

A turn that ends in a question, or with the work half done, is left alone:
`the work is not finished; keeping it`. In the middle of a long turn the line
reads `a piece of the work is finished; compacting`: taskcut ends the turn
before Claude's next request, compacts, and sends `Continue.` in your place —
the transcript shows it as a message from the taskcut plugin — and the work
carries on. Nothing you type mentions taskcut.

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
instead, and leaves what a compaction keeps to Claude Code. The job that needs
it most is the one nobody watches: a list of tasks handed over in one message,
worked through in one turn that runs for hours.

## Install it for a whole project, or everywhere

```bash
# this repository, for everyone who clones it
claude plugin marketplace add wasd96040501/taskcut --scope project
claude plugin install taskcut@taskcut --scope project

# every session on this machine
claude plugin marketplace add wasd96040501/taskcut
claude plugin install taskcut@taskcut --scope user
```

Start sessions with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`, or put
`"CLAUDE_CODE_ENABLE_FUNCTION_HOOKS": "1"` under `env` in
`~/.claude/settings.json` and start them as usual. Off for one session:
`TASKCUT=0 claude`. To remove it, uninstall with the same `--scope`.

## What it costs

| | |
| --- | --- |
| **Below the floor** | Nothing: no model call, no tool, nothing written. |
| **Each step past it** | One `sonnet` call of at most ~12k tokens in and a sentence out — a few cents. It runs while the step's tools run, so it rarely adds a wait. |
| **Each compaction** | Whatever `/compact` costs, because it is `/compact`. |

Past the floor is a short stretch: a compaction takes the context back under
it, and judging stops until it fills again.

Thirty-six real sqlglot changes, handed to Sonnet 5 in one message and left
to run: taskcut compacted once inside the turn, after issue 20, from 431,567
tokens to 10,511, and carried on. The peak context fell from 71% of the window
to 43%, and the cost by about a fifth; both runs solved all thirty-six.
Whether compacting at boundaries makes long sessions *work* better is what the
benchmark is for: [docs/measurement.md](docs/measurement.md).

## Settings

Both have a working default. Set one at install time with `--config KEY=VALUE`,
or change it later from a session with `/plugin`. Settings are yours, not a
scope's: Claude Code keeps plugin settings in your user settings, so they apply
wherever taskcut is installed on this machine, whatever `--scope` it was
installed with.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `35` | Context fill, as a percentage, below which taskcut does nothing at all: no model is asked and nothing is compacted. A compaction invalidates the prompt cache, so below the floor it costs more than it saves. `0` judges every turn. |
| `model` | `sonnet` | The model that judges whether a step finished a piece of the work — the model auto mode's permission classifier uses by default. `haiku` costs about a third and misses more boundaries. An alias or a full id, resolved the way a `--model` value is. |

## How it works

After each step of the main conversation, and at the end of each turn, taskcut
reads the context fill the status line shows. Below `floorPercent` it stops
there. Past it, it asks `model`, through the hooks API's `$.model.complete`,
whether the step reports a piece of the work complete. The judge reads what
auto mode's permission classifier reads — your messages, the assistant's tool
calls except read-only lookups, and `CLAUDE.md`, never any tool output — plus
the step it is judging: what Claude just said, and the calls it is making or
the reply it stopped on. A step that ends by asking you something is never a
boundary.

On a yes at the end of a turn, taskcut calls `$.session.compact()`, the call
`/compact` makes. On a yes inside a turn, it waits for that step's tools to
finish, ends the turn with `$.turn.abort` before the next request goes out,
compacts the same way, and submits `Continue.` with `$.prompt.submit` — what you
would do yourself with Esc, `/compact` and "continue". On anything else it
leaves the conversation alone.

The source is two files: `hooks/register.ts` (the hooks) and `hooks/judge.ts`
(what the judge reads and asks). [docs/design.md](docs/design.md) has the
reasoning, and the designs this one replaced.

## Limitations

* **Interactive sessions only.** `claude -p` and the SDK transport cannot
  compact, and taskcut never ends a turn there.
* **The judge never sees tool output**, so a reply that claims more than was
  done can fool it. The cost is a compaction a little early.
* **A compaction inside a turn splits it in two.** Claude Code can only
  compact between turns, so taskcut ends the turn and starts the next with
  `Continue.`, which the transcript shows as a message from the plugin. What
  the compaction keeps is the same as at the end of a turn.
* **A prompt typed while the judge runs wins.** The compaction is skipped and
  the next finished turn is judged again.
* **Early access.** The function-hooks API may change between Claude Code
  releases; `make validate` reports anything the engine would refuse.

## Documentation

* [docs/measurement.md](docs/measurement.md) — what the benchmark found.
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

MIT. See [LICENSE](LICENSE).
