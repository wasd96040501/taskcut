"""What the context holds that competes with the work, request by request.

taskcut's floor is a share of the window: a count of tokens. What the
literature finds degrades a long context is less the count than what the
tokens are. Two things matter most, and both can be read off a transcript
without asking a model anything:

  stale      a copy of something that has since changed -- a file shown and
             then edited, a command's output from before it was run again.
             Earlier values of the same thing are what a model retrieves by
             mistake (proactive interference: arXiv 2506.08184), and they are
             exactly what a compaction clears.
  redundant  a second copy of something unchanged. It costs tokens and
             attention, but it cannot contradict the copy beside it.

This module keeps a ledger of every tool output the main thread's context
holds, keyed by what it is a copy of, and reports at every request how much of
it is stale or redundant. A compaction empties the ledger, as it empties the
context. It is a pure function of the transcript's records.

What it cannot see: two *different* things that disagree -- a value set in one
file and overridden in another, a decision reversed in prose. Those need a
reader, not a key, and the `churn` workload exists to measure them with the
answer known in advance.

A key is one of:

  file:<path>     Read, Edit, Write, NotebookEdit; and a Bash command that shows
                  or rewrites one file in a way the patterns below recognise
  cmd:<command>   any other Bash command, normalised, so a rerun of the same
                  tests supersedes the run before
  tool:<name>:<input>   any other tool

Bash is read by pattern, and the patterns are approximate: an edit made by a
Python heredoc that builds its path at run time is missed, and the file keeps
its version. The count of stale copies is therefore a lower bound.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Characters per token, near enough for a share. metrics.CHARS_PER_TOKEN.
CHARS_PER_TOKEN = 4

#: Tools whose input names the one file they read or change.
READS = frozenset({"Read", "NotebookRead"})
CHANGES = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})

#: A path a command might show or change: something with a source-like suffix.
_PATH = r"[\w./~+-]+\.(?:py|pyi|ts|tsx|js|mjs|json|md|txt|toml|cfg|ini|yaml|yml|rst|sh|sql|go|rs|java|c|h|cpp)\b"
_PATH_RE = re.compile(_PATH)

#: Commands that print (part of) a file and nothing else.
_SHOWS = re.compile(r"^(?:cat|nl|head|tail|less|more|bat)\b|^sed\s+-n\b|^awk\b")

#: Ways a command rewrites a file in place. Each captures the path.
_WRITES = [
    re.compile(r"\bsed\s+-i\S*\s+(?:(?:-e\s+)?(?:'[^']*'|\"[^\"]*\"|\S+)\s+)+(" + _PATH + ")"),
    re.compile(r"(?<![0-9&])>>?\s*(" + _PATH + ")"),
    re.compile(r"\btee\s+(?:-a\s+)?(" + _PATH + ")"),
    re.compile(r"open\(\s*['\"](" + _PATH + r")['\"]\s*,\s*['\"][wa]"),
    re.compile(r"Path\(\s*['\"](" + _PATH + r")['\"]\s*\)\.write_(?:text|bytes)"),
    re.compile(r"\bgit\s+(?:checkout|restore)\s+(?:--\s+)?(" + _PATH + ")"),
]

#: Whether a Python heredoc or one-liner writes somewhere. When it does and
#: the path is not a literal the patterns above find, every path the command
#: names is taken as changed: an overcount, but of files the command was about.
_WRITES_SOMEWHERE = re.compile(r"\.write_text\(|\.write\(|open\([^)]*['\"][wa]['\"]|\bsed\s+-i|\bpatch\b|\bgit\s+apply\b")

#: The tail of a command that only trims what it prints.
_TRIM = re.compile(r"\s*(?:2>&1)?\s*(?:\|\s*(?:tail|head)(?:\s+-n)?\s+-?\d+\s*)+$|\s*2>&1\s*$")


@dataclass
class Copy:
    """One tool output in the context: a copy of `key` at `version`."""

    key: str
    version: int
    chars: int


@dataclass(frozen=True)
class Point:
    """The ledger as it stood when one request was sent."""

    #: One-based, over the main thread's requests.
    request: int
    #: What the request sent: cache read, cache write and plain input.
    context: int
    #: Tokens of tool output the context held.
    output: int
    #: Of those, copies of something that had changed since.
    stale: int
    #: Of those, second copies of something unchanged.
    redundant: int
    #: Things the context held more than one version of.
    conflicted: int
    #: The most versions of any one thing the context held, and which.
    versions: int
    busiest: str
    #: Compactions before this request.
    cuts: int


@dataclass
class Ledger:
    copies: list[Copy] = field(default_factory=list)
    version: dict[str, int] = field(default_factory=dict)

    def show(self, key: str, chars: int) -> None:
        self.copies.append(Copy(key, self.version.get(key, 0), chars))

    def change(self, key: str) -> None:
        self.version[key] = self.version.get(key, 0) + 1

    def point(self, request: int, context: int, cuts: int) -> Point:
        seen: set[tuple[str, int]] = set()
        stale = redundant = 0
        versions: dict[str, set[int]] = {}
        for copy in self.copies:
            versions.setdefault(copy.key, set()).add(copy.version)
            if copy.version < self.version.get(copy.key, 0):
                stale += copy.chars
            elif (copy.key, copy.version) in seen:
                redundant += copy.chars
            seen.add((copy.key, copy.version))
        busiest = max(versions, key=lambda k: len(versions[k]), default="")
        return Point(
            request=request,
            context=context,
            output=sum(c.chars for c in self.copies) // CHARS_PER_TOKEN,
            stale=stale // CHARS_PER_TOKEN,
            redundant=redundant // CHARS_PER_TOKEN,
            conflicted=sum(1 for v in versions.values() if len(v) > 1),
            versions=len(versions.get(busiest, ())),
            busiest=busiest,
            cuts=cuts,
        )


def _relative(path: str, cwd: str) -> str:
    """A path as the workspace sees it, so `/ws/src/a.py` and `src/a.py` are one key."""
    path = path.strip("'\"")
    for prefix in (cwd.rstrip("/") + "/", "./"):
        if cwd and path.startswith(prefix):
            path = path[len(prefix):]
    return str(Path(path)) if path else path


def _command(command: str) -> str:
    """A Bash command reduced to what it runs: `cd ws &&` and output trimming dropped."""
    text = " ".join(command.split())
    text = re.sub(r"^cd\s+\S+\s*&&\s*", "", text)
    return _TRIM.sub("", text)


def classify(tool: str, payload: dict, cwd: str) -> tuple[list[str], str]:
    """What a call changes, and the key its output is a copy of."""
    if tool in READS | CHANGES and isinstance(payload.get("file_path") or payload.get("notebook_path"), str):
        key = "file:" + _relative(payload.get("file_path") or payload.get("notebook_path"), cwd)
        return ([key] if tool in CHANGES else []), key
    if tool == "Bash":
        command = str(payload.get("command", ""))
        paths = sorted({p for p in (_relative(m, cwd) for m in _PATH_RE.findall(command)) if p not in ("", ".")})
        written = sorted({p for p in (_relative(m, cwd) for pattern in _WRITES for m in pattern.findall(command)) if p not in ("", ".")})
        if not written and _WRITES_SOMEWHERE.search(command):
            written = paths
        changed = ["file:" + p for p in written]
        text = _command(command)
        if _SHOWS.match(text) and len(paths) == 1 and not written:
            return changed, "file:" + paths[0]
        return changed, "cmd:" + text
    return [], f"tool:{tool}:{json.dumps(payload, sort_keys=True)[:200]}"


def _result_chars(block: dict) -> int:
    content = block.get("content")
    if isinstance(content, str):
        return len(content)
    return sum(len(str(part.get("text", ""))) for part in content or [] if isinstance(part, dict))


def series(records) -> list[Point]:
    """The ledger at every request of the main thread, in order."""
    ledger = Ledger()
    pending: dict[str, tuple[str, int]] = {}
    points: list[Point] = []
    seen: set[str] = set()
    cuts = 0
    for record in records:
        if record.get("isSidechain"):
            continue
        if record.get("type") == "system" and record.get("subtype") == "compact_boundary":
            ledger, pending, cuts = Ledger(), {}, cuts + 1
            continue
        message = record.get("message") or {}
        cwd = str(record.get("cwd") or "")
        if record.get("type") == "assistant":
            usage = message.get("usage")
            request_id = record.get("requestId") or message.get("id") or record.get("uuid")
            if usage and request_id not in seen:
                seen.add(request_id)
                context = sum(usage.get(k, 0) for k in ("cache_read_input_tokens", "cache_creation_input_tokens", "input_tokens"))
                points.append(ledger.point(len(points) + 1, context, cuts))
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    payload = block.get("input") if isinstance(block.get("input"), dict) else {}
                    changed, key = classify(str(block.get("name")), payload, cwd)
                    for target in changed:
                        ledger.change(target)
                    # What a Write or an Edit sends is a copy of the new version.
                    sent = len(json.dumps(payload)) if block.get("name") in CHANGES else 0
                    pending[str(block.get("id"))] = (key, sent)
        elif record.get("type") == "user":
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    key, sent = pending.pop(str(block.get("tool_use_id")), (None, 0))
                    if key is None:
                        continue
                    if key.startswith("cmd:") or key.startswith("tool:"):
                        # A rerun: the output before it is now the old one.
                        if any(c.key == key for c in ledger.copies):
                            ledger.change(key)
                    ledger.show(key, _result_chars(block) + sent)
    return points


def load(path: str | Path) -> list[Point]:
    lines = Path(path).read_text(errors="replace").splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return series(records)


#: Absolute paths a key can carry: the home directory, and a session's scratchpad.
_PRIVATE = [(re.compile(r"/private/tmp/claude-\d+/[^/\s]+/[^/\s]+/scratchpad"), "$SCRATCHPAD"), (re.compile(re.escape(str(Path.home()))), "~")]


def scrub(text: str) -> str:
    for pattern, replacement in _PRIVATE:
        text = pattern.sub(replacement, text)
    return text


def summary(points: list[Point]) -> dict:
    """The session in a line: its peak, and what the context held there."""
    if not points:
        return {}
    peak = max(points, key=lambda p: p.context)
    worst = max(points, key=lambda p: p.stale)
    return {
        "requests": len(points),
        "cuts": points[-1].cuts,
        "peak_context": peak.context,
        "peak_output": peak.output,
        "peak_stale": peak.stale,
        "peak_redundant": peak.redundant,
        "peak_conflicted": peak.conflicted,
        "peak_versions": peak.versions,
        "peak_busiest": scrub(peak.busiest)[:120],
        "most_stale": worst.stale,
        "most_stale_at": worst.request,
    }
