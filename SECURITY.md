# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

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

* a path by which the ledger of one session is read by another;
* a transcript the cut can produce that leaks content the person did not intend
  to keep, or that drops content they did;
* anything that lets the `outcome` text a model writes change taskcut's behaviour
  rather than only its stored text.

## What is out of scope

* The function-hooks API itself, and the Claude Code binary. Report those to
  [anthropics/claude-code](https://github.com/anthropics/claude-code/issues).
* Losing context you wanted to keep because a conclusion was written too thinly.
  taskcut keeps what the model wrote; judging sufficiency is not something it
  claims to do.
