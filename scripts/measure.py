#!/usr/bin/env python3
"""Per-request token accounting for a Claude Code session transcript.

Usage:
    scripts/measure.py <session.jsonl> [<session.jsonl> ...]

Transcripts live in ~/.claude/projects/<slugified-cwd>/<session-id>.jsonl. Each
assistant record carries the usage block the API returned, which is the only
honest source for what a session cost: the status line rounds, and the naive sum
of the three input counters bills cached tokens at full price.

The weighted total is in base-input-token equivalents, using the published cache
multipliers: a cache write costs about 1.25 of a base input token and a cache
read about 0.1. Output is reported separately because it is priced on its own
scale.

A streamed assistant message appears in the transcript more than once, every
copy carrying the same usage block, so records are deduplicated by request id
before anything is added up.
"""

import json
import sys

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def records(path):
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except ValueError:
            continue


def report(path):
    print(f"=== {path}")
    header = f"{'#':>3} {'read':>8} {'write':>8} {'in':>5} {'out':>6}  what"
    print(header)
    print("-" * len(header))

    seen = set()
    n = read_total = write_total = input_total = output_total = 0
    boundaries = compactions = 0

    for record in records(path):
        message = record.get("message") or {}

        if record.get("type") == "user":
            content = message.get("content")
            if isinstance(content, list):
                if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
                    continue
                text = " ".join(
                    str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                text = str(content)
            if text.lstrip().startswith("The working context of"):
                compactions += 1
                label = "<< taskcut cut"
            else:
                label = f"USER: {text.strip()[:52]}"
            print(f"{'':>3} {'':>8} {'':>8} {'':>5} {'':>6}  {label}")
            continue

        usage = message.get("usage")
        if not usage:
            continue
        request_id = record.get("requestId") or message.get("id") or record.get("uuid")
        if request_id in seen:
            continue
        seen.add(request_id)

        n += 1
        read = usage.get("cache_read_input_tokens", 0)
        write = usage.get("cache_creation_input_tokens", 0)
        plain = usage.get("input_tokens", 0)
        out = usage.get("output_tokens", 0)
        read_total += read
        write_total += write
        input_total += plain
        output_total += out

        tools = [b.get("name") for b in (message.get("content") or []) if isinstance(b, dict) and b.get("type") == "tool_use"]
        mark = ""
        if any(str(t).endswith("close_task") for t in tools):
            boundaries += 1
            mark = "   <<< close_task"
        print(f"{n:>3} {read:>8} {write:>8} {plain:>5} {out:>6}  {','.join(str(t) for t in tools) or '(text)'}{mark}")

    weighted = input_total + CACHE_WRITE_MULTIPLIER * write_total + CACHE_READ_MULTIPLIER * read_total
    print("-" * len(header))
    print(f"{'':>3} {read_total:>8} {write_total:>8} {input_total:>5} {output_total:>6}  TOTAL over {n} requests")
    print()
    print(f"  weighted input : {weighted:>12,.0f}  (in + 1.25*write + 0.1*read)")
    print(f"  naive sum      : {input_total + write_total + read_total:>12,.0f}  (bills cached tokens at full price)")
    print(f"  output         : {output_total:>12,}")
    print(f"  boundaries     : {boundaries:>12}  close_task calls")
    # Not the number of cuts: a cut writes the whole post-cut message list, so
    # a ledger message written by an earlier cut is recorded again by the next.
    print(f"  ledger msgs    : {compactions:>12}  (>= the number of cuts)")
    print()
    return weighted


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    totals = [report(p) for p in sys.argv[1:]]
    if len(totals) == 2:
        a, b = totals
        print(f"arm 1 / arm 2 = {a / b:.2f}x weighted input" if b else "arm 2 is empty")


if __name__ == "__main__":
    main()
