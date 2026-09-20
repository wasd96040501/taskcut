# taskcut

[![CI](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml/badge.svg)](https://github.com/wasd96040501/taskcut/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

A [Claude Code](https://claude.com/claude-code) mod that compacts the
conversation at sub-task boundaries instead of at the context limit.

## The problem

Claude Code compacts when the context window fills. On a job that runs for hours
or days, that threshold almost never lines up with the shape of the work. It
fires in the middle of a sub-task, summarising away detail that is still live
while keeping detail from work that finished an hour ago. The moment when "what
still matters" has a clean answer — the end of a sub-task — passes without
anything happening.

A long job is a sequence of shorter ones. Once a piece of work is done, the files
that were read for it, the commands that were run, and the approaches that were
abandoned are dead weight. What has to survive is the conclusion.

## What taskcut does

It gives the model a tool, `close_task`, and asks it to call the tool when a
sub-task is finished. The argument is the conclusion, and it is the only thing
that survives.

At the end of that turn, if the context window has filled past a configurable
floor, taskcut compacts the conversation itself. The replacement transcript is:

* every human turn, kept **verbatim** by its engine handle — nothing the person
  said is ever paraphrased, and the turn that set the standing task is always
  among them;
* one message holding the ledger of closed sub-tasks and their conclusions.

No summariser runs. The cut is a deterministic function of the transcript, so it
costs no model call and loses nothing it claims to keep.

```
before                              after
──────────────────────────────      ──────────────────────────────
user: "do sub-task A"               user: "do sub-task A"        (verbatim)
assistant: reads 9 files            user: "do sub-task C"        (verbatim)
user:      tool results             user: [ledger]
assistant: runs 4 commands                1. [CLOSED] sub-task A
user:      tool results                      -> a.txt is the manifest; ...
assistant: close_task(...)                2. [CLOSED] sub-task B
user:      tool result                       -> the retry path was the bug; ...
assistant: "done"
user: "do sub-task B"
... 30 more messages ...
```

The engine's own threshold compaction stays in place as the safety net for a
sub-task too large to reach a boundary. taskcut does not intercept it; it only
hands the summariser the ledger, so the model is not asked to re-derive what is
already settled.

## Requirements

* Claude Code **2.1.278** or newer.
* An **interactive** session. `$.session.compact` is unavailable in a headless
  one, so `claude -p` and the stream-json SDK transport cannot compact. A
  terminal session and a `claude --bg` session both qualify. See
  [docs/design.md](docs/design.md#where-taskcut-can-run) for the measurements.
* While function hooks are in early access, `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`.
  This is Claude Code's own flag, not taskcut's, and it will go away when the
  feature graduates. taskcut's behaviour does not depend on it; see
  [docs/compatibility.md](docs/compatibility.md).

## Install

```bash
claude plugin marketplace add wasd96040501/taskcut
claude plugin install taskcut@taskcut --scope project   # this repository
claude plugin install taskcut@taskcut --scope user      # your machine
```

Updating is `claude plugin update taskcut@taskcut`; removing is
`claude plugin uninstall taskcut@taskcut`. `--scope` takes `user`, `project`
(recorded in `.claude/settings.json`, shared with the team) or `local`
(`.claude/settings.local.json`, just you). A private repository works the same
way: the clone uses your git credentials.

From a checkout instead — for a private or air-gapped copy, where the
marketplace has to come from a local path:

```bash
git clone https://github.com/wasd96040501/taskcut.git
cd taskcut && ./scripts/install.sh
```

Installing does not make taskcut do anything yet. It is inert until a session
opts in.

## Try it in five minutes

In a scratch directory, so nothing on your machine changes outside it:

```bash
mkdir /tmp/taskcut-demo && cd /tmp/taskcut-demo
printf 'alpha\nbeta\ngamma\n' > notes.txt
printf 'one\ntwo\n' > data.txt

claude plugin marketplace add wasd96040501/taskcut --scope local
claude plugin install taskcut@taskcut --scope local --config floorPercent=0
touch .taskcut

CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude
```

`floorPercent=0` is the part that matters for a demo. The default is 40: below
that, taskcut records the conclusion and leaves the transcript alone, because
working context still small enough to carry is worth more than the room a cut
would free. A five-minute trial never gets near 40% of the window, so without
this you would see nothing happen and reasonably conclude it was broken.

Then, in the session, one sub-task at a time:

```
> Count the lines in notes.txt and cat it. Then call close_task.
> Count the lines in data.txt and cat it. Then call close_task.
> Without running any tool: what do you have about the earlier sub-tasks, and
  can you still see the raw wc and cat output?
```

After each `close_task` the transcript is replaced and the status line shows
`Conversation compacted`. By the third message the model has the conclusions and
not the tool output it drew them from. `ctx` stays where it started instead of
climbing.

Undo it:

```bash
claude plugin uninstall taskcut@taskcut --scope local
claude plugin marketplace remove taskcut --scope local
rm -rf /tmp/taskcut-demo
```

## Turning it on

taskcut defaults to **opt-in**: installed but inert, in every session, until
something says otherwise. Three things can say otherwise, in this order of
precedence:

| | Scope | |
| --- | --- | --- |
| `TASKCUT=0` | one session | Off, whatever else says. The kill switch. |
| `TASKCUT=1` | one session | On, for that session only. |
| `activation` = `always` | wherever installed | On in every session. |
| `.taskcut` at the project root | one repository | On in that repository. |

The usual way is the marker file, because the repository then carries the
decision and a reviewer can see it:

```bash
cd ~/src/the-repo
touch .taskcut
git add .taskcut && git commit -m "chore: enable taskcut"
```

For one session, without changing anything on disk:

```bash
TASKCUT=1 claude
```

And to run it everywhere, if that is what you want:

```bash
claude plugin install taskcut@taskcut --scope user --config activation=always
```

### Why taskcut owns this instead of leaving it to the platform

Claude Code gates every hooks module behind `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS`
today, and that flag is off by default. It would be easy to treat it as taskcut's
safety switch, and wrong: it is an early-access flag, so it will default to on or
disappear when function hooks graduate. A plugin whose inertness rested on it
would go from inert to active everywhere, silently, on an unrelated Claude Code
release.

So the decision is taskcut's own, and it is deny by default. The state before
`session.start` has run is inert, which means a session where that hook never
fires does nothing rather than everything. `TASKCUT=0` outranks every other
input. Both are covered by tests in `test/activation.test.ts`.

### What it touches when it is on

| | |
| --- | --- |
| Adds to the model's tools | `mcp__taskcut__close_task` |
| Reads | the project root, `TASKCUT`, the session id, the context-fill percentage, its own store |
| Writes | its own plugin store, under `~/.claude/plugins/store/` |
| Changes | the transcript, at a boundary, once the context is past `floorPercent` |
| Never touches | your files, your settings, the network |

That is not a promise, it is the output of a static scan. Check it yourself:

```bash
claude plugin validate .
```

It prints every engine call the module can make, including through helpers, and
every environment variable it reads. A hooks module has no filesystem, network or
process access of its own; everything goes through that interface.

## Configuration

Every setting has a working default. Change them under `/config`, in the
`taskcut` section.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `40` | Context fill, as a percentage, below which a closed sub-task is recorded but no cut is made. Below the floor the working context is still small enough to carry, and a cut would trade all of it for the ledger alone. Set to `0` to cut at every boundary. |
| `recentHumanTurns` | `2` | How many of the most recent human turns are kept beside the first one. Human turns are unbounded on a long run, so keeping all of them only moves the growth. |
| `ledgerVerbatim` | `12` | How many closed sub-tasks stay in the model's own words. Past this, the oldest are folded into one rolled-up entry. |
| `foldModel` | `haiku` | The model that folds them. An alias or a full id, resolved the way a `--model` value is. |

## How it is put together

| File | Role |
| --- | --- |
| `hooks/register.ts` | Every hook, and every call on the engine interface. |
| `hooks/ledger.ts` | The ledger and the keep-set rule, as pure functions. |
| `hooks/activation.ts` | Whether taskcut runs at all, as a pure rule. |
| `hooks/config.ts` | Settings, with defaults for anything unset. |
| `test/` | Unit tests for the three modules above. `./scripts/test.sh`. |

The split is not stylistic. A hooks module may pass `$` only to a function
declared in the same file; the loader refuses a module that passes it across an
import. So everything that touches the engine lives in `register.ts`, and
everything that can be reasoned about as plain data lives beside it.

## Limitations

* **Interactive sessions only.** See Requirements.
* **The conclusion is only as good as what the model wrote.** taskcut keeps the
  `outcome` text exactly; it does not check that the text is sufficient. A thin
  conclusion produces a thin context.
* **No assistant message survives a cut.** The kept set is human turns and the
  ledger. After a cut the model cannot see what it said in the turn that just
  ended, so a follow-up phrased as *the approach you just described* has nothing
  to resolve against. On a long autonomous run this is the point; in a
  conversation it is a cost, and it is the reason the floor is not zero.
* **One session per process.** The activation decision and the pending-boundary
  flag are module state. Claude Code loads a hooks module once per session
  process, so this holds today, but it is an assumption the API does not
  guarantee.
* **Early access.** The function-hooks API may change between Claude Code
  releases without notice. Re-run `scripts/validate.sh` after upgrading; it
  reports anything the engine would refuse before a session loads the plugin.
  See [docs/compatibility.md](docs/compatibility.md).

## Documentation

* [docs/design.md](docs/design.md) — why the cut is shaped this way, what was
  measured, and the constraints that produced each rule.
* [docs/troubleshooting.md](docs/troubleshooting.md) — what to check when
  nothing is being compacted.
* [docs/compatibility.md](docs/compatibility.md) — what taskcut depends on, what
  a Claude Code upgrade can break, and what semantic versioning covers here.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are
welcome.

## License

Apache License 2.0. See [LICENSE](LICENSE).
