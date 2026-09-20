"""A finished session, parsed into plain records.

Claude Code writes one JSON object per line to
``~/.claude/projects/<slugified-cwd>/<session-id>.jsonl``. This module turns that
into turns and requests and stops there: it applies no policy, knows nothing
about taskcut beyond recognising the message a cut leaves behind, and every
metric is computed from what it returns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

#: The opening words of the message taskcut puts in place of what it dropped.
#: Recognising it is what lets a metric count cuts and skip the message when
#: segmenting turns; it is the one piece of plugin knowledge in this module.
LEDGER_OPENING = "The working context of"


@dataclass
class Request:
    """The usage block of one model response.

    Usage and content are counted separately and deliberately. A response is
    written to the transcript as several records -- one per content block, a
    thinking block and a tool_use block and a text block each on their own line
    -- and every one of them repeats the same usage. Counting usage once per
    response is therefore right, and dropping the records that repeat it throws
    away most of what the assistant actually did.
    """

    read: int
    write: int
    plain: int
    output: int


@dataclass
class Turn:
    """A human prompt and everything the assistant did before the next one."""

    prompt: str
    requests: list[Request] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @property
    def answer(self) -> str:
        return " ".join(t.strip() for t in self.texts if t.strip()).strip()


@dataclass
class Transcript:
    path: Path
    turns: list[Turn] = field(default_factory=list)
    #: Ledger messages seen. A cut rewrites the whole message list, so an earlier
    #: cut's message is recorded again by the next one: this is an upper bound on
    #: the number of cuts, not the number itself.
    ledger_messages: int = 0

    @property
    def requests(self) -> list[Request]:
        return [r for t in self.turns for r in t.requests]

    def turn_for(self, prompt: str) -> Turn | None:
        """The turn that actually answered `prompt`.

        A prompt can appear several times. A cut re-emits the human turns it
        kept, so a copy of a recent prompt reappears with nothing under it, and
        a cut that happens *after* a prompt was answered leaves that dead copy
        last. Taking the last match therefore finds an empty turn and scores a
        correct answer as wrong. The last match that has an answer is the one
        that ran; the bare last match is the fallback for a prompt that was
        never answered at all.
        """
        matches = [t for t in self.turns if t.prompt.strip() == prompt.strip()]
        if not matches:
            return None
        answered = [t for t in matches if t.requests or t.answer]
        return answered[-1] if answered else matches[-1]


def _text_of(message: dict) -> tuple[str, bool]:
    """The message's text, and whether it carried any tool_result block."""
    content = message.get("content")
    if not isinstance(content, list):
        return str(content or ""), False
    has_result = any(b.get("type") == "tool_result" for b in content if isinstance(b, dict))
    text = " ".join(
        str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
    )
    return text, has_result


def load(path: str | Path) -> Transcript:
    path = Path(path)
    out = Transcript(path=path)
    seen: set[str] = set()
    current: Turn | None = None

    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") or {}

        if record.get("type") == "user":
            text, has_result = _text_of(message)
            if has_result:
                continue  # the answer half of a tool call, not a human turn
            text = text.strip()
            if text.startswith(LEDGER_OPENING):
                out.ledger_messages += 1
                continue
            current = Turn(prompt=text)
            out.turns.append(current)
            continue

        if current is None:
            continue

        # Content from every record: each carries a different block.
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                current.tools.append(str(block.get("name")))
            elif block.get("type") == "text":
                current.texts.append(str(block.get("text", "")))

        # Usage once per response.
        usage = message.get("usage")
        if not usage:
            continue
        request_id = record.get("requestId") or message.get("id") or record.get("uuid")
        if request_id in seen:
            continue
        seen.add(request_id)
        current.requests.append(
            Request(
                read=usage.get("cache_read_input_tokens", 0),
                write=usage.get("cache_creation_input_tokens", 0),
                plain=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
            )
        )

    return out


def find(project_root: str | Path, workspace: str | Path) -> Path:
    """The newest transcript Claude Code wrote for a workspace.

    The project directory is the workspace's absolute path with every character
    that is not a letter, a digit or a hyphen replaced by a hyphen.
    """
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in str(Path(workspace).resolve()))
    directory = Path(project_root) / slug
    sessions = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise FileNotFoundError(f"no transcript under {directory}")
    return sessions[-1]
