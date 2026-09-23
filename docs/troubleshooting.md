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

Whether the module loaded is in Claude Code's debug log, whatever the context
fill:

```bash
claude -p ok --debug-file /tmp/taskcut.log >/dev/null
grep 'taskcut@taskcut' /tmp/taskcut.log
```

`hooks module taskcut@taskcut loaded` means it is running. `not loaded:` is
followed by the reason; without the flag, it says the rollout flag is off.

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

`floorPercent` defaults to 35. Below that taskcut does nothing at all, because a
cut re-caches the kept set at full price and that costs more than a small
transcript saves. The status line's `ctx N%` is the figure being compared, and
`/plugin` shows the floor in force. It is one value for the whole machine:
Claude Code keeps plugin settings in your user settings, whatever scope the
plugin was installed at.

### 5. What did the judge say?

Past the floor, every compaction taskcut makes gets a dim line:

```
taskcut: context at 43%, compacting before the next piece
```

Every other judgement is silent. `/taskcut` counts them, and `claude --debug`
shows each one, with what it cost:

```
context at 41%, step judged the same work [judge sonnet: in=1834 cache_read=0 cache_write=0 out=52 ms=2140]
context at 43%, step judged a new piece [judge sonnet: in=1902 cache_read=0 cache_write=0 out=47 ms=1810]
context at 44%, could not judge the step (api-error 429 rate_limit) [judge sonnet: in=0 cache_read=0 cache_write=0 out=0 ms=310]
```

A judgement that could not be made keeps the context, and says why. The end of a turn is never
judged, even when everything you asked for is done: what you say next may be
about it, and `/compact` before new work is yours. The judge reads your
messages, the assistant's latest messages, what its latest calls touched and
its task list, plus the step it is judging -- never any tool output, and not
`CLAUDE.md`. A step that does not itself say a piece is done is not a
boundary, however plainly the work shows it.

### 6. Nothing is compacted inside a long turn

Only an interactive session ends a turn early: a `-p` run or an SDK transport
never does. In a terminal session or `claude --bg`, look for this line:

```
taskcut: turn.step hook skipped: ran past its 10s budget
```

It means the engine skipped the step hook, and on that step taskcut could not
act. Report it with your Claude Code version.

## It compacts on every turn

The context after a compaction -- the summary, the recent messages Claude Code
keeps, the system prompt and tool definitions -- is still past `floorPercent`.
taskcut then waits until the context has grown five points past what the
compaction left before judging again, so this takes a floor lower than what a
compaction leaves, typically a few percent: raise `floorPercent`.

## A message from the taskcut plugin says `Continue.`

That is taskcut picking the work back up after compacting inside a turn:
Claude Code compacts only between turns, so taskcut ended the turn, compacted,
and started the next one. It is what you would do yourself with Esc,
`/compact` and "continue".

## A compaction's summary answers a question instead

A compaction right after a request that ended on your own message -- a reply
Claude gave without using a tool, say -- answers that message in place of a
summary, on Claude Code 2.1.280, `/compact` typed by hand included. taskcut
compacts only after a step that followed tool results, so one it made cannot
do this.

## Something was lost in a compaction

What a compaction keeps is Claude Code's, exactly as for `/compact`; taskcut
only chose the moment. If the moment was wrong -- the judge took a step for the
move to the next piece when it was not -- `claude --debug` shows the step it
judged. The judge never reads tool output, so a reply that claims more than
was done can fool it.

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
