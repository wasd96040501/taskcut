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
* Function hooks enabled: `export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`.
  The feature is early access and off by default.
* An **interactive** session. `$.session.compact` is unavailable in a headless
  one, which means `claude -p` and the stream-json SDK transport cannot compact.
  A terminal session and a `claude --bg` session both qualify. See
  [docs/design.md](docs/design.md#where-taskcut-can-run) for the measurements.

## Quickstart

One line, using the GitHub CLI you are already signed in with (the repository is
private, so the fetch has to carry credentials):

```bash
bash <(gh api repos/wasd96040501/taskcut/contents/scripts/bootstrap.sh \
         -H "Accept: application/vnd.github.raw")
```

That keeps a checkout at `~/.claude/src/taskcut` and runs the installer. Or clone
it yourself:

```bash
gh repo clone wasd96040501/taskcut
cd taskcut
./scripts/install.sh
```

The installer copies the plugin to `~/.claude/skills/taskcut`, where Claude Code
loads it automatically as `taskcut@skills-dir` from the next session on. Confirm
it with:

```bash
claude plugin list | grep -A3 taskcut
```

Then start a session and use it:

```
> Work through the plan in PLAN.md. Call close_task after each step.
```

To try it without installing anything:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir /path/to/taskcut
```

To remove it:

```bash
~/.claude/src/taskcut/scripts/uninstall.sh   # or ./scripts/uninstall.sh from a checkout
```

## Controlling where it runs

taskcut has two independent switches. Both have to be on for anything to happen,
which makes the blast radius easy to reason about.

### 1. The master switch

Function hooks are early access and off by default. Without
`CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`, taskcut still shows as installed in
`claude plugin list`, but its hooks module is never loaded: the `close_task` tool
does not exist and no hook runs.

| | `mcp__taskcut__close_task` offered? |
| --- | --- |
| `claude` | no |
| `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude` | yes |

So the narrowest possible setup is to export nothing and keep an alias for the
sessions where you want it:

```bash
alias cct='CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude'
```

Exporting the variable in your shell profile turns it on for every session. That
is the widest setting, and it enables every hooks-module plugin you have
installed, not only this one.

### 2. Per-repository

Install it switched off, and let each repository turn it on:

```bash
./scripts/install.sh --opt-in
```

That leaves `"taskcut@skills-dir": false` in `~/.claude/settings.json`. In a
repository where you do want it:

```bash
cd ~/src/the-repo
claude plugin enable taskcut@skills-dir --scope project   # .claude/settings.json, shared with the team
claude plugin enable taskcut@skills-dir --scope local     # .claude/settings.local.json, just you
```

Project settings override user settings, and Claude Code says so:

```
Status: ✔ loaded
Note: Disabled in ~/.claude/settings.json but still loads — project settings
      enable it, which overrides your user setting
```

The reverse works too: leave it on for yourself and put
`"taskcut@skills-dir": false` in the projects that should not have it.

### 3. Neither — run it from a checkout

Nothing installed, nothing in settings, one session only:

```bash
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude --plugin-dir ~/.claude/src/taskcut
```

### What it touches when it is on

| | |
| --- | --- |
| Adds to the model's tools | `mcp__taskcut__close_task` |
| Reads | the session id, the context-fill percentage, its own store |
| Writes | its own plugin store, under `~/.claude/plugins/store/` |
| Changes | the transcript, at a boundary, once the context is past `floorPercent` |
| Never touches | your files, your settings, the network |

`claude plugin validate ~/.claude/skills/taskcut` prints the complete list of
engine calls this plugin can make. A hooks module has no filesystem, network or
process access of its own; everything goes through that interface.

## Configuration

Every setting has a working default. Change them under `/config`, in the
`taskcut` section.

| Setting | Default | What it controls |
| --- | --- | --- |
| `floorPercent` | `40` | Context fill, as a percentage, below which a closed sub-task is recorded but no cut is made. A compaction invalidates the prompt cache, so cutting a small context costs more than it saves. Set to `0` to cut at every boundary. |
| `recentHumanTurns` | `2` | How many of the most recent human turns are kept beside the first one. Human turns are unbounded on a long run, so keeping all of them only moves the growth. |
| `ledgerVerbatim` | `12` | How many closed sub-tasks stay in the model's own words. Past this, the oldest are folded into one rolled-up entry. |
| `foldModel` | `haiku` | The model that folds them. An alias or a full id, resolved the way a `--model` value is. |

## How it is put together

| File | Role |
| --- | --- |
| `hooks/register.ts` | Every hook, and every call on the engine interface. |
| `hooks/ledger.ts` | The ledger and the keep-set rule, as pure functions. |
| `hooks/config.ts` | Settings, with defaults for anything unset. |

The split is not stylistic. A hooks module may pass `$` only to a function
declared in the same file; the loader refuses a module that passes it across an
import. So everything that touches the engine lives in `register.ts`, and
everything that can be reasoned about as plain data lives beside it.

## Limitations

* **Interactive sessions only.** See Requirements.
* **The conclusion is only as good as what the model wrote.** taskcut keeps the
  `outcome` text exactly; it does not check that the text is sufficient. A thin
  conclusion produces a thin context.
* **Early access.** The function-hooks API may change between Claude Code
  releases without notice. Pin a release and re-run `scripts/validate.sh` after
  upgrading.

## Documentation

* [docs/design.md](docs/design.md) — why the cut is shaped this way, what was
  measured, and the constraints that produced each rule.
* [docs/troubleshooting.md](docs/troubleshooting.md) — what to check when
  nothing is being compacted.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and pull requests are
welcome.

## License

Apache License 2.0. See [LICENSE](LICENSE).
