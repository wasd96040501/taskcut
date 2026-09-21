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

`floorPercent` defaults to 40. Below that, a closed sub-task is recorded in the
ledger and the transcript is deliberately left alone, because a cut re-caches
the kept set at full price and that costs more than a small transcript saves.
The status line's `ctx N%` is the figure being compared. To cut at every
boundary, set `floorPercent` to `0` with `/plugin`, or reinstall with
`--config floorPercent=0`.

### 5. Is the model calling the tool?

The cut is driven by `close_task`. If the model never calls it there is no
boundary to cut at. Ask for it directly:

> Work through the plan. Call close_task after each step.

Or put it in the project's `CLAUDE.md`.

## The model redid work that was already finished

Check that the ledger is keyed by session:

```bash
python3 -c "import json,glob;[print(list(json.load(open(f)).keys())) for f in glob.glob('$HOME/.claude/plugins/store/taskcut*.json')]"
```

Every key should read `ledger:<session-uuid>`. A bare `ledger` key means an older
build is installed, and two sessions on this machine are sharing one ledger.
Reinstall from a current checkout.

## A conclusion came out too thin

taskcut keeps the `outcome` text exactly as written; it does not judge whether
the text is sufficient. If conclusions are coming back thin, the lever is the
instruction, not the plugin — tell the model what a conclusion has to contain for
this project, in `CLAUDE.md`.

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
