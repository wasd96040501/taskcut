# taskcut

[![CI](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml/badge.svg)](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) plugin that compacts the
conversation when the work moves on from one sub-task to the next, instead of
when the context window fills.

```
  without taskcut                          with taskcut
  ───────────────────────────────────      ───────────────────────────────────
  you:  "do A, B and C"                    you:  "do A, B and C"
        ... A's work ...                         ... A's work ...
        ... B's work ...                         A done, on to B
        ... C's work, half-way                   ── compacted ──
        ── window full ──                        ... B's work ...
        ── compacted ──                          B done, on to C
        C's live detail                          ── compacted ──
        summarised away                          ... C's work ...
                                                 C done: kept, it is yours now
```

taskcut changes **when** Claude Code compacts, not how. Once the context is
past a floor, a model judges each step Claude takes for whether the work is
moving on from a finished piece to another, reading what you asked for and
where Claude has got to, never any tool output. If it is, taskcut runs Claude
Code's own compaction, the one `/compact` runs. A piece being finished is not
enough: when the last thing you asked for is done, nothing has moved on yet,
and what you say next may well be about it. Hand over twenty tasks in one
message and walk away, and it compacts between them, not after the last. Once
a turn has ended the work is back with you, and so is `/compact`. Below the
floor it does nothing at all and costs nothing, and nothing in your prompts
has to mention it.

## Try it

Needs Claude Code **2.1.278 or newer**; developed and measured on 2.1.280. In a project you work on — installed for
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
figure in the status line. From then on, when Claude finishes one of the things
you asked for and moves on to the next, a dim line says so:

```
taskcut: context at 43%, compacting before the next piece
```

taskcut ends the turn before Claude's next request, compacts exactly as
`/compact` would, and sends `Continue.` in your place — the transcript shows it
as a message from the taskcut plugin — and the work carries on. A step that
asks you something, works on a piece not yet finished, or finishes the last
thing you asked for is left alone. Nothing you type mentions taskcut.

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
| **Each step Claude explains past it** | One `sonnet` call and a sentence out. What goes in is your messages, Claude's latest messages, what its latest commands touched and the step it is taking, never any output: about two thousand tokens however long the session has run, uncached (`$.model.complete` marks no cache point) — about half a cent. It runs while the step's tools run, so it rarely adds a wait. |
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
| `model` | `sonnet` | The model that judges whether the work moves on to another piece — the model auto mode's permission classifier uses by default. `haiku` costs about a third and misses more boundaries. An alias or a full id, resolved the way a `--model` value is. |

## How it works

After each step of the main conversation, taskcut reads the context fill the
status line shows. Below `floorPercent` it stops there. Past it, it asks
`model`, through the hooks API's `$.model.complete`, whether the work moves on
from a finished piece to another at that step. The judge reads what says so
and little else: every message you sent (the first and the latest few whole,
the rest cut to a line), Claude's latest messages, what its latest calls
touched — a file, or what a command says it does, never the call in full — its
task list if it keeps one, and the step it is judging: what Claude just said
and the calls it is making. Never any tool output, and not `CLAUDE.md`. A step
that asks you something is never a boundary, and the end of a turn is never
judged.

On a yes, taskcut waits for that step's tools to finish, ends the turn with
`$.turn.abort` before the next request goes out, calls `$.session.compact()` —
the call `/compact` makes — and submits `Continue.` with `$.prompt.submit`:
what you would do yourself with Esc, `/compact` and "continue". On anything
else it leaves the conversation alone.

The source is two files: `hooks/register.ts` (the hooks) and `hooks/judge.ts`
(what the judge reads and asks). [docs/design.md](docs/design.md) has the
reasoning, and the designs this one replaced.

## Limitations

* **Interactive sessions only.** `claude -p` and the SDK transport cannot
  compact, and taskcut never ends a turn there.
* **The judge never sees tool output**, so a reply that claims more than was
  done can fool it. The cost is a compaction a little early.
* **A compaction inside a turn splits it in two.** Claude Code compacts only
  between turns, so taskcut ends the turn and starts the next with
  `Continue.`, which the transcript shows as a message from the plugin. What
  the compaction keeps is the same as `/compact` keeps.
* **Only inside a turn.** taskcut compacts between the pieces of one turn's
  work. Once the turn ends, a new piece starts with your next message, and
  `/compact` before it is yours to run; Claude Code's own threshold still
  applies.
* **Not in a turn's first step.** On Claude Code 2.1.280 a compaction right
  after a request that ended on your own message — `/compact` typed by hand
  included — answers that message instead of summarising the conversation, so
  taskcut compacts only after a step that followed tool results.
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
