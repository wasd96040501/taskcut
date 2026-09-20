"""Parsing is where a benchmark quietly lies, so it is tested against the shape
Claude Code actually writes rather than the shape it seems to write."""

import json
import tempfile
import unittest
from pathlib import Path

from taskcut_eval import transcript


def write(records) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for record in records:
        handle.write(json.dumps(record) + "\n")
    handle.close()
    return Path(handle.name)


def user(text, tool_result=False):
    content = [{"type": "tool_result", "tool_use_id": "t", "text": text}] if tool_result else [{"type": "text", "text": text}]
    return {"type": "user", "message": {"role": "user", "content": content}}


def assistant(request_id, blocks, usage=None):
    message = {"role": "assistant", "content": blocks}
    if usage is not None:
        message["usage"] = usage
    return {"type": "assistant", "requestId": request_id, "message": message}


USAGE = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 30}


class OneResponseManyRecords(unittest.TestCase):
    """A response is written out one content block per line, and every line
    repeats the same usage. Counting usage per line inflates the bill; counting
    content per response throws most of it away."""

    def setUp(self):
        self.path = write([
            user("do the thing"),
            assistant("req_1", [{"type": "thinking", "thinking": "..."}], USAGE),
            assistant("req_1", [{"type": "tool_use", "name": "Bash", "input": {}}], USAGE),
            assistant("req_1", [{"type": "text", "text": "the answer is 42"}], USAGE),
        ])
        self.loaded = transcript.load(self.path)

    def test_usage_is_counted_once(self):
        self.assertEqual(len(self.loaded.requests), 1)
        self.assertEqual(self.loaded.requests[0].read, 1000)

    def test_every_content_block_is_kept(self):
        turn = self.loaded.turns[0]
        self.assertEqual(turn.tools, ["Bash"])
        self.assertIn("42", turn.answer)


class Segmentation(unittest.TestCase):
    def test_a_tool_result_is_not_a_human_turn(self):
        loaded = transcript.load(write([user("first"), user("output", tool_result=True), user("second")]))
        self.assertEqual([t.prompt for t in loaded.turns], ["first", "second"])

    def test_a_ledger_message_is_counted_not_segmented(self):
        loaded = transcript.load(write([
            user("first"),
            user(f"{transcript.LEDGER_OPENING} 2 closed sub-task(s) was dropped"),
            user("second"),
        ]))
        self.assertEqual([t.prompt for t in loaded.turns], ["first", "second"])
        self.assertEqual(loaded.ledger_messages, 1)

    def test_a_repeated_prompt_resolves_to_the_live_one(self):
        # A cut re-emits the human turns it kept, so an early prompt reappears
        # with no answer under it. Only the last copy is the one that ran.
        loaded = transcript.load(write([
            user("what is it"),
            assistant("req_1", [{"type": "text", "text": "stale"}], USAGE),
            user("what is it"),
            assistant("req_2", [{"type": "text", "text": "fresh"}], USAGE),
        ]))
        self.assertEqual(loaded.turn_for("what is it").answer, "fresh")


if __name__ == "__main__":
    unittest.main()
