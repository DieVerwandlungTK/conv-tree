"""Where each open Claude pane currently sits in the prompt tree."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .graph import ConvGraph
from .herdr import ClaudePane


@dataclass
class Markers:
    current: str | None = None
    others: set[str] = field(default_factory=set)


def markers(graph: ConvGraph, panes: list[ClaudePane]) -> Markers:
    m = Markers()
    for p in panes:
        leaf = graph.last_uuid_by_session.get(p.session_id) if p.session_id else None
        prompt = graph.prompt_of(leaf) if leaf else None
        if prompt is None:
            continue
        if p.focused:
            m.current = prompt
        else:
            m.others.add(prompt)
    if m.current is not None:
        m.others.discard(m.current)
    return m


def pane_at(graph: ConvGraph, panes: list[ClaudePane], prompt_uuid: str,
            statuses: tuple[str, ...] | None = None) -> str | None:
    """A Claude pane whose latest position is `prompt_uuid` (optionally only in `statuses`)."""
    for p in panes:
        leaf = graph.last_uuid_by_session.get(p.session_id) if p.session_id else None
        if leaf and (statuses is None or p.status in statuses) and graph.prompt_of(leaf) == prompt_uuid:
            return p.pane_id
    return None


def idle_pane_at(graph: ConvGraph, panes: list[ClaudePane], prompt_uuid: str) -> str | None:
    """A ready (idle/done) Claude pane whose latest position is `prompt_uuid`, if any."""
    return pane_at(graph, panes, prompt_uuid, ("idle", "done"))


def effective_focus(panes: list[ClaudePane], last_focused: str | None) -> tuple[list[ClaudePane], str | None]:
    """Treat the last-focused Claude pane as focused while focus is elsewhere.

    Returns the adjusted panes and the new last-focused pane id.
    """
    focused = next((p.pane_id for p in panes if p.focused), None)
    if focused is not None:
        return panes, focused
    target = last_focused if any(p.pane_id == last_focused for p in panes) else None
    if target is None and len(panes) == 1:
        target = panes[0].pane_id
    if target is None:
        return panes, last_focused
    return [replace(p, focused=p.pane_id == target) for p in panes], target
