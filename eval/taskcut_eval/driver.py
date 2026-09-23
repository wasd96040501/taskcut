"""Runs one session and returns where it was recorded.

This is the only module that touches a terminal, a subprocess or the clock, and
nothing outside it depends on how any of that works. It exists because
``$.session.compact`` is unavailable in a headless session: ``claude -p`` and the
SDK transport cannot compact, so a benchmark driven through either would measure
the plugin doing nothing. A pseudo-terminal gives the engine the interactive
surface it requires.

The screen is never parsed for results. It is used only to notice the
folder-trust prompt and to tell when a turn has gone quiet; every number comes
from the transcript afterwards.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import termios
import time
from pathlib import Path

from . import transcript
from .arms import Arm
from .transcript import PROJECTS
from .workload import Workload

ANSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[=>()][A-Za-z0-9]?|\r")

#: Variables Claude Code sets for a child session. Left in place, the new
#: session is treated as a continuation of this one and gets neither its own
#: session id nor an interactive surface.
INHERITED = (
    "CLAUDECODE",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_PID",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_EFFORT",
)

#: Reading is enough for a workload that only inspects. One that builds needs
#: to write and to run what it wrote, so the set is wider and the workspace is
#: per arm and per model, thrown away between runs.
#: Bash is allowed outright rather than by a list of commands. A workload built
#: on a real repository runs that repository's own tooling -- a virtual
#: environment's interpreter, its test runner -- and a permission denial the
#: benchmark did not intend would be measured as the model failing. The
#: workspace is a throwaway copy, per arm and per model.
TOOLS = "Bash,Read,Grep,Glob,Write,Edit"

#: Nobody is at the keyboard to answer a dialog. A model that asks through one
#: would wait on it until the run times out; asked in text, its question is
#: part of the answer the benchmark reads.
DENIED = "AskUserQuestion"


def prepare_plugin(arm: Arm, source: Path, destination: Path) -> Path:
    """A copy of the plugin with the arm's settings baked into its manifest.

    ``--plugin-dir`` takes no ``--config``, so a setting can only be changed by
    editing a manifest. Copying rather than editing in place keeps a benchmark
    from mutating the repository it is measuring.
    """
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "eval", "node_modules"))
    manifest_path = destination / ".claude-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    for key, value in arm.config.items():
        if key not in manifest["userConfig"]:
            raise KeyError(f"{arm.name}: plugin has no setting {key!r}")
        manifest["userConfig"][key]["default"] = value
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return destination


class Session:
    def __init__(self, cwd: Path, plugin: Path | list[Path] | None, env: dict, model: str, cols: int = 120, rows: int = 40,
                 debug_file: Path | None = None):
        # A workspace reused across runs keeps the transcripts of the earlier
        # ones, under the same project directory. This session's is the one
        # that was not there before it started.
        self.transcripts = transcript.directory(PROJECTS, cwd)
        self.earlier = set(self.transcripts.glob("*.jsonl"))
        self.master, slave = pty.openpty()
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        environment = dict(os.environ)
        for name in INHERITED:
            environment.pop(name, None)
        environment["CLAUDE_CODE_FORCE_SESSION_PERSISTENCE"] = "1"
        environment["CLAUDE_CODE_ENABLE_FUNCTION_HOOKS"] = "1"
        environment["TERM"] = "xterm-256color"
        environment["COLUMNS"], environment["LINES"] = str(cols), str(rows)
        environment.update(env)
        # The debug log is the only record of what taskcut's judge spent: its
        # calls are in neither the transcript nor Claude Code's cost ledger.
        debug = ["--debug-file", str(debug_file)] if debug_file else []
        # One plugin, several (a harness plugin beside the one measured), or none.
        plugins = [plugin] if isinstance(plugin, Path) else list(plugin or [])
        plugin_dirs = [arg for p in plugins for arg in ("--plugin-dir", str(p))]
        self.process = subprocess.Popen(
            # No plugin directory is a session with whatever is installed, the way
            # a person would start one.
            [_binary(), *plugin_dirs, "--model", model, "--allowedTools", TOOLS, "--disallowedTools", DENIED, *debug],
            cwd=str(cwd),
            env=environment,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        self.buffer = b""

    def read_until_quiet(self, quiet: float = 4.0, timeout: float = 300) -> bool:
        deadline = time.time() + timeout
        last = time.time()
        while time.time() < deadline:
            ready, _, _ = select.select([self.master], [], [], 0.3)
            if ready:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                self.buffer += chunk
                last = time.time()
            elif time.time() - last >= quiet:
                return True
        return False

    def screen(self, tail: int = 4000) -> str:
        return ANSI.sub(b"", self.buffer).decode("utf-8", "replace")[-tail:]

    def accept_trust_prompt(self) -> bool:
        """The folder-trust prompt defaults to "No, exit", so a bare Enter kills
        the session before it has done anything."""
        if "trustthisfolder" not in self.screen(3000).replace(" ", "").lower():
            return False
        os.write(self.master, b"\x1b[B")
        time.sleep(0.3)
        os.write(self.master, b"\r")
        self.read_until_quiet(quiet=3.0, timeout=90)
        return True

    def turns_done(self) -> int:
        """How many turns the session has finished, as its transcript records
        them: Claude Code writes one `turn_duration` line as each turn ends."""
        mine = [p for p in self.transcripts.glob("*.jsonl") if p not in self.earlier]
        return sum(p.read_text(errors="replace").count('"subtype":"turn_duration"') for p in mine)

    def ask(self, text: str, timeout: float = 1800, settle: float = 8.0) -> bool:
        """Sends one prompt and waits for its turn to end.

        The end of a turn is read from the transcript, not the screen. A model
        can think, or wait on a long tool, for longer than any quiet period is
        safe to assume, and a prompt typed into a turn that is still running is
        queued behind it: every later step then lands in the wrong turn, and
        closing the session kills the one still working.

        After the turn ends the screen is let settle, so that whatever runs at
        the end of a turn -- a plugin's own work included -- finishes before the
        next prompt starts another.
        """
        before = self.turns_done()
        for character in text:
            os.write(self.master, character.encode())
            time.sleep(0.004)
        time.sleep(0.4)
        os.write(self.master, b"\r")
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.read_until_quiet(quiet=1.0, timeout=2.0)
            if self.turns_done() > before:
                return self.read_until_quiet(quiet=settle, timeout=120)
        return False

    def last_reply(self) -> str:
        """The text of the last assistant message the transcript holds."""
        mine = [p for p in self.transcripts.glob("*.jsonl") if p not in self.earlier]
        reply = ""
        for path in mine:
            for line in path.read_text(errors="replace").splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") != "assistant":
                    continue
                texts = [b.get("text", "") for b in (record.get("message") or {}).get("content") or []
                         if isinstance(b, dict) and b.get("type") == "text"]
                if any(t.strip() for t in texts):
                    reply = "\n".join(texts)
        return reply

    def close(self) -> None:
        try:
            os.write(self.master, b"\x03")
            time.sleep(0.2)
            os.write(self.master, b"\x04")
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
        try:
            os.close(self.master)
        except OSError:
            pass


def _binary() -> str:
    found = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not Path(found).exists():
        raise FileNotFoundError("claude binary not found on PATH")
    return found


def _log(message: str) -> None:
    print(message, flush=True)   # a benchmark runs for a long time unattended


#: How long one message's worth of work may run before the benchmark gives up
#: on it: long enough for hours of unattended work, short of forever.
LONG_TURN_TIMEOUT = 8 * 3600


def _one_message(session: Session, workload: Workload, log) -> None:
    """The whole job as one message, and nobody at the keyboard after it.

    A model may still stop before the job is done -- to report, or to ask. The
    benchmark then sends the workload's nudge, the same words under every arm,
    and counts on the transcript to show how often it had to.
    """
    log(f"  task settled={session.ask(workload.task, timeout=LONG_TURN_TIMEOUT)}")
    for n in range(1, workload.max_nudges + 1):
        if workload.done_marker and workload.done_marker in session.last_reply():
            return
        log(f"  nudge {n}/{workload.max_nudges} settled={session.ask(workload.nudge, timeout=LONG_TURN_TIMEOUT)}")


def run(workload: Workload, arm: Arm, workspace: Path, plugin: Path, model: str, log=_log,
        debug_file: Path | None = None) -> None:
    """Drives one workload under one arm. Results are read from the transcript,
    and what the judge spent from the debug log."""
    session = Session(workspace, plugin, {**dict(workload.env), **arm.env}, model, debug_file=debug_file)
    try:
        session.read_until_quiet(quiet=3.0, timeout=120)
        if session.accept_trust_prompt():
            log("trusted the workspace")
        log(f"boot: {workload.name} / {arm.name}")

        if workload.task:
            _one_message(session, workload, log)
            return

        # The briefing is its own turn, before any work. It is the standing task
        # and the place any global rule is set, and it is the turn taskcut keeps
        # whatever else it drops -- so a rule set here is a test of that.
        if workload.briefing:
            log(f"  briefing settled={session.ask(workload.briefing)}")

        # Every arm gets the same words. Nothing in a prompt may tell the model
        # taskcut is there: whatever it needs from the model, it asks for itself.
        for index, step in enumerate(workload.steps(), 1):
            log(f"  step {index}/{len(workload.files)} settled={session.ask(step)}")

        # Nothing here says whether to use a tool. Whether the model goes back to
        # the source is the measurement, so the prompt must not push it either way.
        for probe in workload.probes:
            log(f"  probe {probe.id} settled={session.ask(probe.question)}")
    finally:
        session.close()
