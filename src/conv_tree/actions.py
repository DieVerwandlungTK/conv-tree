"""Open forks and merges in a new herdr pane beside the anchor pane."""
from __future__ import annotations

import secrets
from pathlib import Path

from .forking import write_fork
from .graph import ConvGraph, PromptNode


READY_TIMEOUT_MS = 120_000


class AgentNotReady(RuntimeError):
    """The new Claude is waiting on a dialog; nothing was typed into it."""


def _start(h, cwd: str, anchor_pane: str, sid: str | None) -> str:
    pane = h.split(anchor_pane, "right", cwd)
    # `agent start` needs a name; drop it right away so herdr lists the pane as plain "claude".
    # Everything after this targets the pane id.
    h.start_claude(f"ct-{(sid or secrets.token_hex(4))[:8]}", pane, ["--resume", sid] if sid else [])
    h.clear_name(pane)
    return pane


def _open(h, cwd: str, anchor_pane: str, sid: str | None) -> str:
    pane = _start(h, cwd, anchor_pane, sid)
    # Never type into a confirmation dialog: wait for the user to answer it.
    if not h.wait_ready(pane, READY_TIMEOUT_MS):
        raise AgentNotReady("the new Claude pane is waiting on a dialog; nothing was sent")
    return pane


def prepare_fork(graph: ConvGraph, project_dir: Path, node: PromptNode) -> str | None:
    """Write the fork file ending just before `node` (None for a root prompt)."""
    parent = graph.records[node.uuid].parent
    return write_fork(graph, project_dir, parent) if parent in graph.records else None


def open_fork(h, cwd: str, anchor_pane: str, sid: str | None, prompt: str) -> str:
    pane = _open(h, cwd, anchor_pane, sid)
    h.type_text(pane, prompt)
    return pane


def prepare_open(graph: ConvGraph, project_dir: Path, node: PromptNode) -> str:
    """Session to resume at `node` (including its result): an existing session that ends
    there, otherwise a new fork file."""
    ending = graph.sessions_ending_at(node.uuid)
    return ending[0] if ending else write_fork(graph, project_dir, graph.last_record_under(node.uuid))


def open_session(h, cwd: str, anchor_pane: str, sid: str) -> str:
    """Resume `sid` in a new pane; nothing is typed, so no need to wait for dialogs."""
    return _start(h, cwd, anchor_pane, sid)


def prepare_merge(graph: ConvGraph, project_dir: Path, a: PromptNode) -> str:
    """Write the fork file for branch A including A's result."""
    return write_fork(graph, project_dir, graph.last_record_under(a.uuid))


def open_merge(h, cwd: str, anchor_pane: str, sid: str, text: str) -> str:
    pane = _open(h, cwd, anchor_pane, sid)
    h.prompt(pane, text)
    return pane


def fork_here(graph: ConvGraph, project_dir: Path, cwd: str, node: PromptNode, h, anchor_pane: str) -> str:
    """Branch just before `node`; its prompt is typed (unsent) into the new pane."""
    return open_fork(h, cwd, anchor_pane, prepare_fork(graph, project_dir, node), node.text)


def merge_into(graph: ConvGraph, project_dir: Path, cwd: str, a: PromptNode, text: str, h, anchor_pane: str) -> str:
    """Open branch A (including its result) and send `text` as the first message."""
    return open_merge(h, cwd, anchor_pane, prepare_merge(graph, project_dir, a), text)
