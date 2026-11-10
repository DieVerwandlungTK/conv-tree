import json
from factory import rec, write_session
from conv_tree.graph import ConvGraph
import pytest
from conv_tree.actions import AgentNotReady, fork_here, merge_into


class FakeHerdr:
    def __init__(self):
        self.calls = []

    def split(self, pane, direction, cwd):
        self.calls.append(("split", pane, direction, cwd))
        return "w:new"

    def start_claude(self, name, pane, args):
        self.calls.append(("start_claude", name, pane, list(args)))

    def clear_name(self, pane):
        self.calls.append(("clear_name", pane))

    def type_text(self, pane, text):
        self.calls.append(("type_text", pane, text))

    def prompt(self, target, text):
        self.calls.append(("prompt", target, text))

    ready = True

    def wait_ready(self, name, timeout_ms):
        self.calls.append(("wait_ready", name, timeout_ms))
        return self.ready


def setup(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None, text="u1 text"), rec("a1", "u1", "assistant"),
                                   rec("u2", "a1", text="u2 text"), rec("a2", "u2", "assistant"),
                                   rec("t2", "a2", toolUseResult={}), rec("a2b", "t2", "assistant")])
    g = ConvGraph(tmp_path)
    g.refresh()
    root = g.forest()[0]
    return g, root, root.children[0]


def jsonl_uuids(p):
    return [json.loads(l)["uuid"] for l in p.read_text().splitlines()]


def test_fork_here_cuts_before_and_types_prompt(tmp_path):
    g, _, u2 = setup(tmp_path)
    h = FakeHerdr()
    assert fork_here(g, tmp_path, "/cwd", u2, h, "w:anchor") == "w:new"
    split, start, clear, wait, typed = h.calls
    assert clear == ("clear_name", "w:new")  # herdr shows "claude", not the temp name
    assert wait == ("wait_ready", "w:new", 120_000)
    assert split == ("split", "w:anchor", "right", "/cwd")
    sid = start[3][1]
    assert start == ("start_claude", f"ct-{sid[:8]}", "w:new", ["--resume", sid])
    assert typed == ("type_text", "w:new", "u2 text")
    assert jsonl_uuids(tmp_path / f"{sid}.jsonl") == ["u1", "a1"]


def test_fork_at_root_starts_fresh(tmp_path):
    g, u1, _ = setup(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    h = FakeHerdr()
    fork_here(g, tmp_path, "/cwd", u1, h, "w:anchor")
    _, start, _, _, typed = h.calls
    assert start[3] == [] and start[1].startswith("ct-") and len(start[1]) == 11
    assert typed == ("type_text", "w:new", "u1 text")
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_merge_into_includes_a_and_sends(tmp_path):
    g, _, u2 = setup(tmp_path)
    h = FakeHerdr()
    merge_into(g, tmp_path, "/cwd", u2, "SUMMARY", h, "w:anchor")
    split, start, clear, _, prompt = h.calls
    sid = start[3][1]
    assert clear == ("clear_name", "w:new")
    assert prompt == ("prompt", "w:new", "SUMMARY")
    assert jsonl_uuids(tmp_path / f"{sid}.jsonl") == ["u1", "a1", "u2", "a2", "t2", "a2b"]


def test_blocked_agent_gets_no_text(tmp_path):
    g, _, u2 = setup(tmp_path)
    h = FakeHerdr()
    h.ready = False
    with pytest.raises(AgentNotReady):
        fork_here(g, tmp_path, "/cwd", u2, h, "w:anchor")
    with pytest.raises(AgentNotReady):
        merge_into(g, tmp_path, "/cwd", u2, "SUMMARY", h, "w:anchor")
    assert not [c for c in h.calls if c[0] in ("type_text", "prompt")]
