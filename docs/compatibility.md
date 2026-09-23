# Compatibility

## What taskcut depends on

taskcut is built on Claude Code's function-hooks API, which is early access. The
declarations it is written against are generated per Claude Code version by
`/plugin-types`, and the first line of that file names the version that wrote it.

| Depends on | Kind | If it changes |
| --- | --- | --- |
| `session.start`, `turn.step`, `turn.complete` | hook events | taskcut stops working; `claude plugin validate` reports the unknown event before a session loads it |
| `$.session.usage`, `$.session.messages`, `$.session.compact`, `$.env.get`, `$.model.complete`, `$.turn.abort`, `$.prompt.submit`, `$.ui.log` | engine calls | same: refused at load, named in the validation output |
| what `$.session.messages` holds: a compaction's summary opening with "This session is being continued from a previous conversation", a plugin's prompt with "The … plugin sent a message", a background task's report with `<task-notification>` | text Claude Code writes | the judge would read such a message as something you asked for; it is still shown the step, so the cost is a request misread, not a crash |
| a hook's budget counting only its own code, not its `$` calls | engine rule | the judgement inside a step would overrun it, and the engine would skip the hook: taskcut would compact only at the end of a turn, and say so in the transcript |
| what `$.model.complete` resolves to | data shape | `claude plugin validate` does not see it; only `tsc` against regenerated types does. 2.1.278, which taskcut was measured on, resolved the reply's text; 2.1.280 resolves `{ isAnswered, text, usage }`, and 0.8.0 read that object as text, so every judgement failed and nothing was ever compacted. The reply is now taken as `unknown` and read by `readReply`, which knows both shapes and treats anything else as no reply |
| a compaction after a request that ended on the person's words answering them instead of summarising | engine bug, 2.1.280 | taskcut never ends a turn at its first step; when it is fixed, that guard can go |
| `$.model.complete` sending no cache breakpoint | engine behaviour, 2.1.280 | little: the judge reads about two thousand tokens, and a cache would save a fraction of a cent; see [the judge's prompt cache](design.md#the-judges-prompt-cache) |
| `session.start`'s `isInteractive` | data shape | taskcut would stop ending turns early, and so would not compact at all |
| `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` | early-access flag | **nothing**, by design — see below |

## The early-access flag is not a dependency

Today no hooks module loads unless `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` is set,
and the flag is off by default. That makes it tempting to treat as taskcut's
safety switch. It is not one, and taskcut does not use it as one.

An early-access flag exists to be removed. When function hooks graduate it will
default to on, or stop being read at all. A plugin that relied on it to stay
inert would become active in every session on an unrelated Claude Code release,
with no change to the plugin and nothing for the user to notice.

So consent is the install: a session runs taskcut because someone installed it
for that scope, and `TASKCUT=0` switches off a single session. Removing the flag
changes when the module is *loaded*; it does not change where taskcut was
installed, and `TASKCUT=0` remains a kill switch either way.

## Version support

| taskcut | Claude Code |
| --- | --- |
| unreleased | 2.1.278 and newer; measured on 2.1.280 |
| 0.7.x | 2.1.278 and newer |
| 0.6.x | 2.1.278 and newer |
| 0.5.x | 2.1.278 and newer |
| 0.4.x | 2.1.278 and newer |

Older releases do not have the function-hooks API this is written against.

## After a Claude Code upgrade

```bash
claude            # then, in the session:
/plugin-types     # regenerates .claude/types for the new version
```

then, from a checkout:

```bash
./scripts/validate.sh
```

`claude plugin validate` reads the module the way the engine will and reports
every event and call the engine would refuse, before a session tries to load it.
`scripts/test.sh` covers the logic that does not touch the engine at all, so it
keeps passing across Claude Code versions and tells you the failure is in the
integration rather than in the rules.

## Semantic versioning

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
For a plugin, the public surface that a major version protects is:

* the `userConfig` keys and their meanings;
* the `TASKCUT` switch;
* that a compaction taskcut triggers is Claude Code's own, as `/compact` runs it.

Changing when taskcut judges a piece of work finished is a minor-version
change: it is the point of the plugin, and it is governed by the settings above.
