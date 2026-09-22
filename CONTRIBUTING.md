# Contributing to taskcut

Thanks for taking the time to contribute.

## Before you start

taskcut is built on Claude Code's function-hooks API, which is early access and
may change between releases without notice. Before changing any code under
`hooks/`, regenerate the type declarations for the Claude Code version you are
running:

```bash
claude   # then, in the session:
/plugin-types
```

This writes `.claude/types/claude-code.d.ts`, which `tsconfig.json` already
includes. The file is generated, version-specific, and deliberately not checked
in; the first line of it names the Claude Code version that wrote it.

## Development setup

```bash
git clone https://github.com/wasd96040501/taskcut.git
cd taskcut
export CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1
./scripts/validate.sh
```

Run the plugin from source, without installing it, while you work:

```bash
claude --plugin-dir "$PWD"
```

## The one structural rule

A hooks module may pass `$` only to a function declared at the top level of the
same file. The loader refuses a module that passes it across an import, and
`scripts/validate.sh` reports this before a session ever loads the plugin:

```
$ is passed to "readLedger", imported from "./ledger": $ is followed only into a
function declared in this same file, never across an import
```

So: anything that calls the engine belongs in `hooks/register.ts`. Anything that
is a function of plain data belongs in `hooks/ledger.ts` or `hooks/config.ts`,
where it can be read and reasoned about on its own.

## Tests

```bash
./scripts/test.sh
```

Node 22.18 or newer runs the TypeScript sources directly, so there is nothing to
install and no build step. The suite covers the three modules that do not touch
the engine: the keep-set rule, the activation rule, and settings parsing. Those
are the parts where a mistake is silent, so a change to any of them needs a test
that would have caught the old behaviour.

The hooks themselves are covered by `claude plugin validate`, which reads the
module the way the engine will, and by running the plugin in a real session.

## Before opening a pull request

1. `./scripts/validate.sh` passes with no errors. It runs the tests too.
2. `tsc -p tsconfig.json` passes, with the type declarations regenerated for your
   Claude Code version.
3. You have run the change in a real interactive session. `claude -p` cannot
   exercise the compaction path — it is unavailable in a headless session — so a
   change to the cut has not been tested until it has run in a terminal.
4. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
   `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

## Changes to the keep-set

The keep-set rule is the part of this project where a mistake is expensive and
quiet, so it gets its own bar.

A user message carrying `tool_result` blocks answers the assistant message that
made the calls. A transcript that keeps one half of that pair and drops the other
is rejected by the API, and the failure surfaces at the next model request rather
than at the cut. Any change to `boundedHumanTurns` or `humanTurnsOf` must state,
in a comment, why the pairs still travel together.

## Reporting bugs

Open an issue with the template. Please include the output of `claude --version`,
whether the session was interactive or headless, and the last few lines of
`claude plugin validate .`.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By
participating, you are expected to uphold it.

## License

By contributing, you agree that your contributions will be licensed under the
MIT License, the same license that covers this project.
