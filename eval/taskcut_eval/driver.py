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

from .arms import Arm
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

TOOLS = (
    "Bash(cat:*),Bash(grep:*),Bash(sed:*),Bash(head:*),Bash(tail:*),Bash(wc:*),"
    "Bash(awk:*),Bash(find:*),Read,Grep,Glob,mcp__taskcut__close_task"
)


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
    def __init__(self, cwd: Path, plugin: Path, env: dict, model: str, cols: int = 120, rows: int = 40):
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
        self.process = subprocess.Popen(
            [_binary(), "--plugin-dir", str(plugin), "--model", model, "--allowedTools", TOOLS],
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

    def ask(self, text: str, quiet: float = 7.0, timeout: float = 480) -> bool:
        for character in text:
            os.write(self.master, character.encode())
            time.sleep(0.004)
        time.sleep(0.4)
        os.write(self.master, b"\r")
        return self.read_until_quiet(quiet=quiet, timeout=timeout)

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


def run(workload: Workload, arm: Arm, workspace: Path, plugin: Path, model: str, log=_log) -> None:
    """Drives one workload under one arm. Results are read from the transcript."""
    session = Session(workspace, plugin, dict(arm.env), model)
    try:
        session.read_until_quiet(quiet=3.0, timeout=120)
        if session.accept_trust_prompt():
            log("trusted the workspace")
        log(f"boot: {workload.name} / {arm.name}")

        for index, step in enumerate(workload.steps(), 1):
            prompt = step
            if arm.closes_tasks:
                prompt += " Then call close_task."
            log(f"  step {index}/{len(workload.files)} settled={session.ask(prompt)}")

        # Nothing here says whether to use a tool. Whether the model goes back to
        # the source is the measurement, so the prompt must not push it either way.
        for probe in workload.probes:
            log(f"  probe {probe.id} settled={session.ask(probe.question)}")
    finally:
        session.close()
