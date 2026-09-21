# Compatibility

## What taskcut depends on

taskcut is built on Claude Code's function-hooks API, which is early access. The
declarations it is written against are generated per Claude Code version by
`/plugin-types`, and the first line of that file names the version that wrote it.

| Depends on | Kind | If it changes |
| --- | --- | --- |
| `session.start`, `tool.call`, `turn.complete`, `session.compact`, `session.end` | hook events | taskcut stops working; `claude plugin validate` reports the unknown event before a session loads it |
| `$.tool.register`, `$.session.compact`, `$.session.usage`, `$.session.id`, `$.session.root`, `$.store.*`, `$.fs.exists`, `$.env.get`, `$.model.complete`, `$.clock.now`, `$.ui.log` | engine calls | same: refused at load, named in the validation output |
| `SessionMessage` carrying an engine `handle` | data shape | the keep-set would stop being verbatim; this is the one that could degrade quietly |
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
| 0.6.x | 2.1.278 and newer |
| 0.5.x | 2.1.278 and newer |
| 0.4.x | 2.1.278 and newer |

Older releases have no `session.compact` hook that answers with `{ messages }`,
and that answer is what the whole design rests on.

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

Changing when taskcut judges a turn finished is a minor-version change: it is
the point of the plugin, and it is governed by the settings above.
