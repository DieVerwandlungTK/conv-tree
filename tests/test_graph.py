import time
from factory import rec, write_session
from conv_tree.graph import ConvGraph, is_prompt, prompt_text


def texts(nodes):
    return [n.text for n in nodes]


def build(tmp_path):
    g = ConvGraph(tmp_path)
    g.refresh()
    return g


def test_linear_conversation(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None), rec("a1", "u1", "assistant"),
                                   rec("u2", "a1"), rec("a2", "u2", "assistant")])
    f = build(tmp_path).forest()
    assert texts(f) == ["u1"]
    assert texts(f[0].children) == ["u2"]
    assert f[0].children[0].parent is f[0]


def test_rewind_branch_in_same_file(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None), rec("a1", "u1", "assistant"),
                                   rec("u2", "a1"), rec("a2", "u2", "assistant"),
                                   rec("u3", "a1")])
    f = build(tmp_path).forest()
    assert texts(f[0].children) == ["u2", "u3"]


def test_fork_across_files_dedup(tmp_path):
    u1, a1 = rec("u1", None), rec("a1", "u1", "assistant")
    write_session(tmp_path, "s1", [u1, a1, rec("u2", "a1")])
    write_session(tmp_path, "s2", [dict(u1, sessionId="s2"), dict(a1, sessionId="s2"),
                                   rec("u4", "a1", session="s2")])
    f = build(tmp_path).forest()
    assert len(f) == 1
    assert f[0].sessions == {"s1", "s2"}
    assert texts(f[0].children) == ["u2", "u4"]


def test_non_prompts_hidden(tmp_path):
    cmd = rec("c1", "a1", text="<command-name>/model</command-name>")
    del cmd["promptSource"]
    write_session(tmp_path, "s1", [
        rec("u1", None), rec("a1", "u1", "assistant"),
        rec("m1", "a1", isMeta=True),
        rec("t1", "m1", toolUseResult={}),
        rec("n1", "t1", promptSource="system"),
        cmd,
        rec("u2", "c1"),
    ])
    f = build(tmp_path).forest()
    assert texts(f) == ["u1"]
    assert texts(f[0].children) == ["u2"]


def test_untagged_plain_prompt_counts():
    r = rec("x", None, text="hello")
    del r["promptSource"]
    assert is_prompt(r)


def test_block_content_with_image():
    r = rec("x", None, text=[{"type": "text", "text": "see"}, {"type": "image", "source": {}}])
    assert is_prompt(r)
    assert prompt_text(r) == "see [image]"


def test_compaction_keeps_tree_connected(tmp_path):
    write_session(tmp_path, "s1", [
        rec("u1", None), rec("a1", "u1", "assistant"),
        rec("b1", None, "system", subtype="compact_boundary", logicalParentUuid="a1"),
        rec("cs", "b1", isCompactSummary=True, text="This session is being continued"),
        rec("u2", "cs"),
    ])
    f = build(tmp_path).forest()
    assert texts(f) == ["u1"]
    assert texts(f[0].children) == ["u2"]


def test_unrelated_trees_newest_first(tmp_path):
    write_session(tmp_path, "s1", [rec("old", None)])
    write_session(tmp_path, "s2", [rec("new", None, session="s2")])
    write_session(tmp_path, "s1", [rec("old2", "old")])  # old tree now has newest activity
    f = build(tmp_path).forest()
    assert texts(f) == ["old", "new"]


def test_last_result(tmp_path):
    write_session(tmp_path, "s1", [
        rec("u1", None), rec("a1", "u1", "assistant", text="first"),
        rec("t1", "a1", toolUseResult={}), rec("a1b", "t1", "assistant", text="final answer"),
        rec("u2", "a1b"), rec("a2", "u2", "assistant", text="other"),
    ])
    g = build(tmp_path)
    assert g.last_result("u1") == "final answer"
    assert g.last_record_under("u1") == "a1b"


def test_refresh_picks_up_appends_and_new_files(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None)])
    g = build(tmp_path)
    write_session(tmp_path, "s1", [rec("a1", "u1", "assistant"), rec("u2", "a1")])
    write_session(tmp_path, "s2", [rec("z1", None, session="s2")])
    assert g.refresh() is True
    assert set(texts(g.forest())) == {"u1", "z1"}
    assert g.refresh() is False


def test_large_session_perf(tmp_path):
    recs, parent = [], None
    for i in range(30_000):
        kind = "user" if i % 6 == 0 else "assistant"
        recs.append(rec(f"r{i}", parent, kind, timestamp="2026-11-10T00:00:00.000Z"))
        parent = f"r{i}"
    write_session(tmp_path, "s1", recs)
    t0 = time.perf_counter()
    g = ConvGraph(tmp_path)
    g.refresh()
    f = g.forest()
    assert time.perf_counter() - t0 < 2.0
    assert len(f) == 1
