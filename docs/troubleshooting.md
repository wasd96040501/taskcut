# Troubleshooting

## Nothing is being compacted

Work down this list; the first four cover almost everything.

### 1. Is it installed for this session, and not switched off?

```bash
claude plugin list        # taskcut should be here
echo "$TASKCUT"           # 0 switches it off for the session; anything else does not
```

taskcut runs wherever it is installed. If `claude plugin list` does not show it,
the install went to a different scope than the directory you are in -- a
`--scope project` install only applies inside that repository.

### 1b. Are function hooks enabled?

```bash
echo "$CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"
```

While function hooks are in early access this must print `1`, or the hooks module
is not loaded at all — the plugin still appears in `claude plugin list`, and none
of its hooks run. This is Claude Code's flag, not taskcut's, and it will stop
being needed when the feature graduates.

### 2. Is the plugin loaded?

```bash
claude plugin list | grep -A3 taskcut
```

You want `Status: ✔ loaded`. If the plugin is absent, check that the marketplace is still configured with
`claude plugin marketplace list`, and note that a plugin change is picked up from
the **next** session, not the running one.

### 2b. Is it disabled in this scope?

```bash
claude plugin list | grep -A5 taskcut
```

`Status: ✘ disabled` means a settings file switched the plugin off, which is a
different thing from taskcut being inert. Re-enable it with
`claude plugin enable taskcut@taskcut --scope project`.

### 3. Is the session interactive?

```
$.session.compact: not available in a headless (-p / SDK) session yet
```

That message in the logs means the session is `claude -p` or an SDK transport.
Neither can compact. Use a terminal session or `claude --bg`. See
[design.md](design.md#where-taskcut-can-run).

### 4. Is the context still below the floor?

`floorPercent` defaults to 40. Below that taskcut does nothing at all, because a
cut re-caches the kept set at full price and that costs more than a small
transcript saves. The status line's `ctx N%` is the figure being compared. To
judge every turn, set `floorPercent` to `0` with `/plugin`, or reinstall with
`--config floorPercent=0`.

### 5. What did the judge say?

Past the floor, every turn the model finished ends with a dim line:

```
taskcut: context at 43%, the work is finished; compacting
taskcut: context at 43%, the work is not finished; keeping it
```

No line at all past the floor means the turn was not judged: it was a
subagent's, or it was interrupted or failed. `not finished` on a turn you
consider done usually means the reply ended by proposing more work or asking a
question. The judge reads what auto mode's permission classifier reads -- your
messages, the assistant's non-read-only tool calls and `CLAUDE.md` -- plus the
reply, and never any tool output.

## It compacts on every turn

The context after a compaction -- the summary, the recent messages Claude Code
keeps, the system prompt and tool definitions -- is still past `floorPercent`,
so the next finished turn is judged and compacted again. It happens only with a
floor lower than what a compaction leaves, typically a few percent: raise
`floorPercent`. At `0`, compacting at every finished turn is what was asked for.

## Something was lost in a compaction

What a compaction keeps is Claude Code's, exactly as for `/compact`; taskcut
only chose the moment. If the moment was wrong -- the judge called a turn
finished that was not -- the dim line for that turn says `finished`. The judge
never reads tool output, so a reply that claims more than was done can fool it.

## After upgrading Claude Code

The function-hooks API is early access and may change between releases. After an
upgrade:

```bash
claude   # then, in the session:
/plugin-types
```

then, from a checkout:

```bash
./scripts/validate.sh
```

`claude plugin validate` reads the module the way the engine will and reports
anything the engine would refuse, before a session tries to load it.

## Collecting information for a bug report

```bash
claude --version
echo "$CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"
claude plugin list | grep -A3 taskcut
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin validate ~/.claude/skills/taskcut
```
