"""Thin wrapper around the herdr CLI."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class HerdrError(RuntimeError):
    pass


def _subprocess_timeout(args: list[str]) -> float:
    """Seconds to allow the herdr process; longer than any --timeout it was given."""
    if "--timeout" in args:
        try:
            return int(args[args.index("--timeout") + 1]) / 1000 + 30
        except (IndexError, ValueError):
            pass
    return 60


def default_runner(args: list[str]) -> dict:
    exe = os.environ.get("HERDR_BIN_PATH", "herdr")
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, timeout=_subprocess_timeout(args))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HerdrError(str(e)) from e
    if p.returncode != 0:
        raise HerdrError((p.stderr or p.stdout).strip() or f"herdr exited {p.returncode}")
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError:
        return {}


class Herdr:
    def __init__(self, runner: Callable[[list[str]], dict] = default_runner):
        self.run = runner

    def agent_list(self) -> list[dict]:
        return self.run(["agent", "list"]).get("result", {}).get("agents", [])

    def foreground_pids(self, pane_id: str) -> list[int]:
        info = self.run(["pane", "process-info", "--pane", pane_id]).get("result", {}).get("process_info", {})
        return [p["pid"] for p in info.get("foreground_processes", []) if "pid" in p]

    def split(self, pane_id: str, direction: str, cwd: str) -> str:
        res = self.run(["pane", "split", pane_id, "--direction", direction, "--cwd", cwd, "--no-focus"])
        return res["result"]["pane"]["pane_id"]

    def start_claude(self, name: str, pane_id: str, args: list[str]) -> None:
        cmd = ["agent", "start", name, "--kind", "claude", "--pane", pane_id]
        if args:
            cmd += ["--", *args]
        self.run(cmd)

    def focus(self, target: str) -> None:
        self.run(["agent", "focus", target])

    def clear_name(self, target: str) -> None:
        self.run(["agent", "rename", target, "--clear"])

    def prompt(self, target: str, text: str) -> None:
        self.run(["agent", "prompt", target, text])

    def wait_ready(self, target: str, timeout_ms: int) -> bool:
        """True once the agent is not blocked on a dialog (e.g. folder trust)."""
        status = self.run(["agent", "get", target]).get("result", {}).get("agent", {}).get("agent_status")
        if status != "blocked":
            return True
        try:
            self.run(["agent", "wait", target, "--until", "idle", "--timeout", str(timeout_ms)])
            return True
        except HerdrError:
            return False

    def type_text(self, pane_id: str, text: str) -> None:
        """Type into the pane's input without pressing Enter.

        send-text writes raw bytes, so a newline would act as Enter; wrapping in
        bracketed-paste markers makes Claude take it as one pasted block.
        """
        self.run(["pane", "send-text", pane_id, f"\x1b[200~{text}\x1b[201~"])


@dataclass
class ClaudePane:
    pane_id: str
    focused: bool
    session_id: str | None
    status: str | None = None  # herdr agent_status: idle / done / working / blocked / unknown


def _session_for(h: Herdr, pane_id: str, sessions: Path) -> str | None:
    for pid in h.foreground_pids(pane_id):
        try:
            return json.loads((Path(sessions) / f"{pid}.json").read_text()).get("sessionId")
        except (OSError, ValueError):
            continue
    return None


def claude_panes(h: Herdr, cwd: str, sessions: Path) -> list[ClaudePane]:
    try:
        out = []
        for a in h.agent_list():
            if a.get("agent") != "claude" or a.get("cwd") != cwd:
                continue
            out.append(ClaudePane(a["pane_id"], bool(a.get("focused")), _session_for(h, a["pane_id"], sessions),
                                  a.get("agent_status")))
        return out
    except (HerdrError, OSError, KeyError):
        return []
