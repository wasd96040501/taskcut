# Security Policy

## Supported versions

Only the latest release is supported: fixes land on `main` and ship in the
next release.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/wasd96040501/taskcut/security/advisories/new),
or by email to the address on the maintainer's GitHub profile. You should get an
acknowledgement within 72 hours and an assessment within seven days.

Please include the Claude Code version, the taskcut version, and the smallest
reproduction you have.

## What is in scope

taskcut runs as a Claude Code plugin with function hooks. A hooks module has no
filesystem, network, or process access of its own; every side effect goes through
the engine interface, and `claude plugin validate .` prints the full list of what
this plugin calls. Reports that matter most:

* a path by which taskcut ends a turn, submits a prompt, or compacts where it
  should do nothing: with `TASKCUT=0`, below the floor, in a `claude -p` or SDK
  session, or in a subagent's loop;
* a prompt taskcut submits that is anything other than `Continue.`;
* a path by which the judge is sent more than it is documented to read -- tool
  output, or files other than the `CLAUDE.md` files already in the context.

## What is out of scope

* The function-hooks API itself, and the Claude Code binary. Report those to
  [anthropics/claude-code](https://github.com/anthropics/claude-code/issues).
* What a compaction keeps. It is Claude Code's own compaction, the one
  `/compact` runs.
* A judge that calls a step finished too early or too late. It never sees tool
  output, so a reply that claims more than was done can fool it; the cost is a
  compaction at the wrong moment, as the README's limitations say.
