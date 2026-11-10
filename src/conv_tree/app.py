"""Textual UI: the conversation tree pane."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Static, TextArea, Tree

from .actions import open_fork, open_merge, open_session, prepare_fork, prepare_merge, prepare_open
from .graph import ConvGraph, PromptNode
from .herdr import ClaudePane, Herdr, claude_panes
from .merge import merge_text
from .paths import DEFAULT_CLAUDE_HOME, project_dir, sessions_dir
from .position import Markers, effective_focus, idle_pane_at, markers, pane_at

LEGEND = "▶ last recorded position  ▷ other panes  ◆ merge source"


def _hhmm(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m/%d %H:%M")
    except ValueError:
        return ""


class MergeScreen(ModalScreen["tuple[str, bool] | None"]):
    """Edit the merge text and choose where it goes.

    Dismisses with (text, direct): direct=True sends to `direct_pane` as is;
    False opens branch A as a new fork in a new pane.
    """
    BINDINGS = [Binding("ctrl+s", "send", "Send"), Binding("ctrl+o", "toggle_mode", "Switch target"),
                Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    MergeScreen { align: center middle; }
    #merge-box { width: 90%; height: 90%; border: round $accent; background: $surface; }
    #merge-box TextArea { height: 1fr; }
    """

    def __init__(self, text: str, direct_pane: str | None = None):
        super().__init__()
        self._text = text
        self.direct_pane = direct_pane
        self.direct = direct_pane is not None  # default: no new fork when possible

    def compose(self) -> ComposeResult:
        with Vertical(id="merge-box"):
            yield Label("Merge text (editable)  ctrl+s: send  ctrl+o: switch target  esc: cancel")
            yield Label(self._mode_text(), id="merge-mode")
            yield TextArea(self._text)

    def _mode_text(self) -> str:
        if self.direct:
            return f"Target: send directly to open pane {self.direct_pane} (no new fork)"
        why = "" if self.direct_pane else " (no idle pane at this point)"
        return f"Target: create a new fork and open it in a new pane{why}"

    def action_toggle_mode(self) -> None:
        if self.direct_pane is None:
            self.notify("No idle pane at this point; only a new fork is available", severity="warning")
            return
        self.direct = not self.direct
        self.query_one("#merge-mode", Label).update(self._mode_text())

    def action_send(self) -> None:
        self.dismiss((self.query_one(TextArea).text, self.direct))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConvTreeApp(App):
    TITLE = "conv-tree"
    CSS = """
    #main { layout: horizontal; height: 1fr; }
    .narrow #main { layout: vertical; }
    #tree { width: 2fr; height: 1fr; }
    #detail { width: 1fr; height: 1fr; border-left: solid $panel; padding: 0 1; overflow-y: auto; }
    .narrow #tree { width: 1fr; height: 2fr; }
    .narrow #detail { width: 1fr; height: 1fr; border-left: none; border-top: solid $panel; }
    #legend { height: 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("o", "open", "Open in pane"),
        Binding("f", "fork", "Fork here"),
        Binding("b", "mark", "Merge source"),
        Binding("m", "merge", "Merge here"),
        Binding("c", "jump", "Jump to current"),
        Binding("s", "toggle_branches", "Branches only"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cwd: str, herdr: Herdr | None = None, claude_home: Path = DEFAULT_CLAUDE_HOME,
                 poll_interval: float = 1.0, branches_only: bool = False):
        super().__init__()
        self.cwd = cwd
        self.herdr = herdr or Herdr()
        self.project_dir = project_dir(cwd, claude_home)
        self.sessions = sessions_dir(claude_home)
        self.graph = ConvGraph(self.project_dir)
        self.poll_interval = poll_interval
        self.branches_only = branches_only
        self.own_pane = os.environ.get("HERDR_PANE_ID")
        self.markers = Markers()
        self.panes: list[ClaudePane] = []
        self.merge_source: str | None = None
        self._last_focused: str | None = None
        self._tree_nodes: dict[str, object] = {}
        self._collapsed: set[str] = set()
        self._prompt_nodes: dict[str, PromptNode] = {}
        self._dirty = True
        self._first = True
        self._polling = False

    # -- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            tree: Tree[PromptNode] = Tree(self.cwd, id="tree")
            tree.show_root = False
            yield tree
            yield Static("", id="detail")
        yield Static(LEGEND, id="legend")
        yield Footer()

    def on_mount(self) -> None:
        self.graph.refresh()
        self._apply(self._safe_panes())
        self.set_interval(self.poll_interval, self._tick)

    def on_resize(self, event) -> None:
        self.set_class(self.size.width < 80, "narrow")

    # -- polling ---------------------------------------------------------
    def _safe_panes(self) -> list[ClaudePane]:
        return claude_panes(self.herdr, self.cwd, self.sessions)

    def _tick(self) -> None:
        try:
            self._dirty |= self.graph.refresh()
        except OSError as e:
            self.notify(str(e), severity="error")
        if self._polling:
            return  # a slow herdr call is still running; don't stack threads
        self._polling = True
        self.run_worker(self._poll_panes, thread=True, group="poll")

    def _poll_panes(self) -> None:
        try:
            panes = self._safe_panes()
        finally:
            self._polling = False
        self.call_from_thread(self._apply, panes)

    def _apply(self, panes: list[ClaudePane]) -> None:
        panes, self._last_focused = effective_focus(panes, self._last_focused)
        self.panes = panes
        m = markers(self.graph, panes)
        if not self._dirty and m == self.markers:
            return
        moved = m.current != self.markers.current
        self.markers = m
        self._dirty = False
        self._rebuild()
        if (self._first or moved) and m.current:
            self.select_uuid(m.current, move_cursor=self._first)
        self._first = False

    # -- tree rendering ----------------------------------------------------
    def _label(self, n: PromptNode) -> Text:
        first = (n.text.splitlines() or [""])[0]
        if len(first) > 80:
            first = first[:79] + "…"
        if n.uuid == self.markers.current:
            prefix, style = "▶ ", "bold reverse"
        elif n.uuid in self.markers.others:
            prefix, style = "▷ ", "bold"
        else:
            prefix, style = "  ", ""
        if n.uuid == self.merge_source:
            prefix = "◆" + prefix[1:]
        t = Text(prefix + first, style=style)
        t.append(f"  {_hhmm(n.timestamp)}", style="dim")
        return t

    def _rebuild(self) -> None:
        tree = self.query_one("#tree", Tree)
        cursor = tree.cursor_node.data.uuid if tree.cursor_node and tree.cursor_node.data else None
        for uuid, tn in self._tree_nodes.items():
            if tn.allow_expand and not tn.is_expanded:
                self._collapsed.add(uuid)
            else:
                self._collapsed.discard(uuid)
        tree.clear()
        self._tree_nodes.clear()
        self._prompt_nodes.clear()
        forest = self.graph.forest()
        # A node's single-child continuation stays at the same indent; only
        # branch heads (and roots when there are several trees) nest.
        head_roots = len(forest) > 1
        stack = [(tree.root, r, True, head_roots) for r in reversed(forest)]
        skipped: dict[int, int] = {}  # id(container) -> hidden nodes pending a "… N more" row
        while stack:
            container, node, head, nests = stack.pop()
            if self.branches_only and not head and not self._keep(node):
                skipped[id(container)] = skipped.get(id(container), 0) + 1
                self._prompt_nodes[node.uuid] = node
                stack.append((container, node.children[0], False, False))
                continue
            if n := skipped.pop(id(container), 0):
                container.add_leaf(Text(f"… {n} more", style="dim"))
            head = nests
            has_kids = (head and node.children) or len(node.children) >= 2
            tn = container.add(self._label(node), data=node, allow_expand=bool(has_kids),
                               expand=node.uuid not in self._collapsed)
            self._tree_nodes[node.uuid] = tn
            self._prompt_nodes[node.uuid] = node
            if len(node.children) == 1:
                stack.append((tn if head else container, node.children[0], False, False))
            elif len(node.children) >= 2:
                stack.extend((tn, c, True, True) for c in reversed(node.children))
        target = self._prompt_nodes.get(cursor) if cursor else None
        while target is not None and target.uuid not in self._tree_nodes:
            target = target.parent  # cursor was on a now-hidden node: nearest shown ancestor
        if target is not None:
            tree.move_cursor(self._tree_nodes[target.uuid])

    def _keep(self, n: PromptNode) -> bool:
        """In branches-only mode: show branch points, leaves and marked nodes."""
        return (len(n.children) != 1 or n.uuid == self.markers.current
                or n.uuid in self.markers.others or n.uuid == self.merge_source)

    def action_toggle_branches(self) -> None:
        self.branches_only = not self.branches_only
        self.notify("Showing branch points only" if self.branches_only else "Showing all prompts")
        self._dirty = True
        self._apply(self.panes)

    def select_uuid(self, uuid: str, move_cursor: bool = True) -> None:
        tn = self._tree_nodes.get(uuid)
        if tn is None:
            return
        p = tn.parent
        while p is not None:
            p.expand()
            p = p.parent
        if move_cursor:
            self.query_one("#tree", Tree).move_cursor(tn)
            self._show_detail(tn.data)

    # -- detail ------------------------------------------------------------
    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if event.node.data is not None:
            self._show_detail(event.node.data)

    def _show_detail(self, n: PromptNode) -> None:
        result = self.graph.last_result(n.uuid)
        if len(result) > 4000:
            result = result[:4000] + "…"
        t = Text()
        t.append("Prompt\n", style="bold underline")
        t.append(n.text + "\n\n")
        t.append("Last result\n", style="bold underline")
        t.append((result or "(none yet)") + "\n\n")
        t.append(f"{_hhmm(n.timestamp)}  sessions: {', '.join(sorted(s[:8] for s in n.sessions))}", style="dim")
        self.query_one("#detail", Static).update(t)

    # -- actions -----------------------------------------------------------
    def _cursor(self) -> PromptNode | None:
        tn = self.query_one("#tree", Tree).cursor_node
        return tn.data if tn is not None else None

    def _anchor(self) -> str | None:
        focused = next((p.pane_id for p in self.panes if p.focused), None)
        return focused or (self.panes[0].pane_id if self.panes else None) or self.own_pane

    def _run_action(self, label: str, prepare, open_) -> None:
        """`prepare` (fast, touches the graph) runs here; `open_` (herdr, may wait) in a thread."""
        anchor = self._anchor()
        if anchor is None:
            self.notify("No pane to open next to (run inside herdr)", severity="error")
            return
        try:
            sid = prepare()
        except OSError as e:
            self.notify(f"{label} failed: {e}", severity="error")
            return

        def work():
            try:
                open_(anchor, sid)
                self.call_from_thread(self.notify, f"{label}: opened in a new pane")
            except Exception as e:  # surface any herdr failure without crashing
                self.call_from_thread(self.notify, f"{label}: {e}", severity="error")

        self.run_worker(work, thread=True, group="action")

    def action_fork(self) -> None:
        n = self._cursor()
        if n is None:
            return
        self._run_action("Fork", lambda: prepare_fork(self.graph, self.project_dir, n),
                         lambda anchor, sid: open_fork(self.herdr, self.cwd, anchor, sid, n.text))

    def action_open(self) -> None:
        n = self._cursor()
        if n is None:
            return
        pane = pane_at(self.graph, self.panes, n.uuid)
        if pane is not None:
            # Already open there: a second Claude on the same session would interleave writes.
            def focus():
                try:
                    self.herdr.focus(pane)
                except Exception as e:
                    self.call_from_thread(self.notify, f"Open: {e}", severity="error")
            self.notify(f"Already open in pane {pane}; switching to it")
            self.run_worker(focus, thread=True, group="action")
            return
        self._run_action("Open", lambda: prepare_open(self.graph, self.project_dir, n),
                         lambda anchor, sid: open_session(self.herdr, self.cwd, anchor, sid))

    def action_mark(self) -> None:
        n = self._cursor()
        if n is None:
            return
        self.merge_source = None if self.merge_source == n.uuid else n.uuid
        self._dirty = True
        self._apply(self.panes)

    def action_merge(self) -> None:
        a = self._cursor()
        b = self._prompt_nodes.get(self.merge_source) if self.merge_source else None
        if a is None or b is None:
            self.notify("Pick a merge source with b first", severity="warning")
            return
        text = merge_text(self.graph, a, b)
        if not text:
            self.notify("Nothing to merge (the source is upstream on the same branch)", severity="warning")
            return

        def done(result: tuple[str, bool] | None) -> None:
            if not result or not result[0]:
                return
            body, direct = result
            if direct:
                self._send_direct(a, body)
            else:
                self._run_action("merge", lambda: prepare_merge(self.graph, self.project_dir, a),
                                 lambda anchor, sid: open_merge(self.herdr, self.cwd, anchor, sid, body))

        self.push_screen(MergeScreen(text, idle_pane_at(self.graph, self.panes, a.uuid)), done)

    def _send_direct(self, a: PromptNode, body: str) -> None:
        # Re-check: the pane may have moved on or started working while the text was edited.
        pane = idle_pane_at(self.graph, self.panes, a.uuid)
        if pane is None:
            self.notify("Not sent: the target pane is busy or has moved on. Start again with m",
                        severity="error")
            return

        def work():
            try:
                self.herdr.prompt(pane, body)
                self.call_from_thread(self.notify, f"merge: sent to pane {pane}")
            except Exception as e:  # surface any herdr failure without crashing
                self.call_from_thread(self.notify, f"merge: {e}", severity="error")

        self.run_worker(work, thread=True, group="action")

    def action_jump(self) -> None:
        if self.markers.current:
            self.select_uuid(self.markers.current)
