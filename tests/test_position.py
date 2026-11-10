import json
from factory import rec, write_session
from conv_tree.graph import ConvGraph
from conv_tree.herdr import Herdr, HerdrError, claude_panes
from conv_tree.position import markers

CWD = "/proj"


class FakeRunner:
    def __init__(self, agents, pids):
        self.agents, self.pids, self.calls = agents, pids, []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["agent", "list"]:
            return {"result": {"agents": self.agents}}
        if args[:2] == ["pane", "process-info"]:
            pane = args[args.index("--pane") + 1]
            return {"result": {"process_info": {"foreground_processes": [{"pid": p} for p in self.pids.get(pane, [])]}}}
        raise AssertionError(args)


def agent(pane, focused, cwd=CWD, kind="claude"):
    return {"agent": kind, "pane_id": pane, "cwd": cwd, "focused": focused}


def sessions(tmp_path, mapping):
    d = tmp_path / "sessions"
    d.mkdir()
    for pid, sid in mapping.items():
        (d / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": sid}))
    return d


def two_sessions(proj):
    write_session(proj, "s1", [rec("u1", None), rec("a1", "u1", "assistant"), rec("u2", "a1")])
    write_session(proj, "s2", [rec("v1", None, session="s2")])
    g = ConvGraph(proj)
    g.refresh()
    return g


def test_current_marker_follows_focused_pane(tmp_path):
    g = two_sessions(tmp_path / "p")
    h = Herdr(FakeRunner([agent("w:p1", True), agent("w:p2", False)], {"w:p1": [11], "w:p2": [22]}))
    panes = claude_panes(h, CWD, sessions(tmp_path, {11: "s1", 22: "s2"}))
    m = markers(g, panes)
    assert m.current == "u2"
    assert m.others == {"v1"}


def test_rewind_leaf_is_last_appended(tmp_path):
    proj = tmp_path / "p"
    write_session(proj, "s1", [rec("u1", None), rec("a1", "u1", "assistant"), rec("u2", "a1"),
                               rec("a2", "u2", "assistant"), rec("u3", "a1")])
    g = ConvGraph(proj)
    g.refresh()
    h = Herdr(FakeRunner([agent("w:p1", True)], {"w:p1": [11]}))
    assert markers(g, claude_panes(h, CWD, sessions(tmp_path, {11: "s1"}))).current == "u3"


def test_other_project_ignored(tmp_path):
    g = two_sessions(tmp_path / "p")
    h = Herdr(FakeRunner([agent("w:p1", True, cwd="/elsewhere")], {"w:p1": [11]}))
    panes = claude_panes(h, CWD, sessions(tmp_path, {11: "s1"}))
    assert panes == []
    assert markers(g, panes).current is None


def test_non_claude_agent_ignored(tmp_path):
    h = Herdr(FakeRunner([agent("w:p1", True, kind="codex")], {"w:p1": [11]}))
    assert claude_panes(h, CWD, sessions(tmp_path, {11: "s1"})) == []


def test_missing_session_file(tmp_path):
    g = two_sessions(tmp_path / "p")
    h = Herdr(FakeRunner([agent("w:p1", True)], {"w:p1": [99]}))
    panes = claude_panes(h, CWD, sessions(tmp_path, {}))
    assert [p.session_id for p in panes] == [None]
    assert markers(g, panes).current is None


def test_herdr_failure_is_empty(tmp_path):
    def boom(args):
        raise HerdrError("down")
    assert claude_panes(Herdr(boom), CWD, sessions(tmp_path, {})) == []


def test_herdr_commands():
    calls = []

    def runner(args):
        calls.append(args)
        return {"result": {"pane": {"pane_id": "w:p9"}}}
    h = Herdr(runner)
    assert h.split("w:p1", "right", "/x") == "w:p9"
    h.start_claude("ct-abc", "w:p9", ["--resume", "S"])
    h.prompt("ct-abc", "hi")
    h.type_text("w:p9", "draft")
    assert calls == [
        ["pane", "split", "w:p1", "--direction", "right", "--cwd", "/x", "--no-focus"],
        ["agent", "start", "ct-abc", "--kind", "claude", "--pane", "w:p9", "--", "--resume", "S"],
        ["agent", "prompt", "ct-abc", "hi"],
        ["pane", "send-text", "w:p9", "\x1b[200~draft\x1b[201~"],
    ]


from conv_tree.herdr import ClaudePane
from conv_tree.position import effective_focus


def test_effective_focus_keeps_last_focused_when_none_focused():
    panes = [ClaudePane("p1", False, "s1"), ClaudePane("p2", False, "s2")]
    out, last = effective_focus(panes, "p2")
    assert [p.focused for p in out] == [False, True] and last == "p2"


def test_effective_focus_updates_last():
    panes = [ClaudePane("p1", True, "s1"), ClaudePane("p2", False, "s2")]
    out, last = effective_focus(panes, "p2")
    assert [p.focused for p in out] == [True, False] and last == "p1"


def test_effective_focus_single_pane_is_current():
    out, last = effective_focus([ClaudePane("p1", False, "s1")], None)
    assert out[0].focused and last == "p1"


def test_effective_focus_last_gone_falls_back_to_none_when_several():
    panes = [ClaudePane("p1", False, "s1"), ClaudePane("p2", False, "s2")]
    out, last = effective_focus(panes, "gone")
    assert not any(p.focused for p in out) and last == "gone"


def test_wait_ready():
    calls = []

    def runner(args):
        calls.append(args)
        if args[:2] == ["agent", "get"]:
            return {"result": {"agent": {"agent_status": "blocked"}}}
        if args[:2] == ["agent", "wait"]:
            raise HerdrError("timeout")
    assert Herdr(runner).wait_ready("ct-1", 5) is False
    assert calls[1] == ["agent", "wait", "ct-1", "--until", "idle", "--timeout", "5"]

    assert Herdr(lambda a: {"result": {"agent": {"agent_status": "idle"}}}).wait_ready("ct-1", 5) is True


def test_subprocess_timeout_exceeds_herdr_timeout():
    from conv_tree.herdr import _subprocess_timeout
    assert _subprocess_timeout(["agent", "list"]) == 60
    assert _subprocess_timeout(["agent", "wait", "x", "--until", "idle", "--timeout", "120000"]) > 120
