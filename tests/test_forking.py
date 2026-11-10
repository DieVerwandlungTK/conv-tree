import json
import pytest
from factory import rec, write_session
from conv_tree.graph import ConvGraph
from conv_tree.forking import write_fork


def load(p):
    return [json.loads(l) for l in p.read_text().splitlines()]


def graph(proj):
    g = ConvGraph(proj)
    g.refresh()
    return g


def test_fork_path_and_session_rewrite(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None), rec("a1", "u1", "assistant"), rec("u2", "a1")])
    sid = write_fork(graph(tmp_path), tmp_path, "a1", "new")
    assert sid == "new"
    out = load(tmp_path / "new.jsonl")
    assert [r["uuid"] for r in out] == ["u1", "a1"]
    assert all(r["sessionId"] == "new" for r in out)
    assert [r["parentUuid"] for r in out] == [None, "u1"]


def test_fork_generates_id(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None)])
    sid = write_fork(graph(tmp_path), tmp_path, "u1")
    assert (tmp_path / f"{sid}.jsonl").exists() and len(sid) == 36


def test_fork_trims_at_compaction(tmp_path):
    write_session(tmp_path, "s1", [
        rec("u1", None), rec("a1", "u1", "assistant"),
        rec("b1", None, "system", subtype="compact_boundary", logicalParentUuid="a1"),
        rec("u2", "b1"), rec("a2", "u2", "assistant"),
    ])
    out = load(tmp_path / f"{write_fork(graph(tmp_path), tmp_path, 'a2')}.jsonl")
    assert [r["uuid"] for r in out] == ["b1", "u2", "a2"]
    assert out[0]["parentUuid"] is None


def test_fork_from_other_file_branch(tmp_path):
    u1, a1 = rec("u1", None), rec("a1", "u1", "assistant")
    write_session(tmp_path, "s1", [u1, a1])
    write_session(tmp_path, "s2", [dict(u1, sessionId="s2"), dict(a1, sessionId="s2"),
                                   rec("u4", "a1", session="s2"), rec("a4", "u4", "assistant", session="s2")])
    out = load(tmp_path / f"{write_fork(graph(tmp_path), tmp_path, 'a4')}.jsonl")
    assert [r["uuid"] for r in out] == ["u1", "a1", "u4", "a4"]


def test_existing_files_untouched(tmp_path):
    p = write_session(tmp_path, "s1", [rec("u1", None), rec("a1", "u1", "assistant")])
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    write_fork(graph(tmp_path), tmp_path, "a1")
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


def test_refuse_overwrite(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None)])
    with pytest.raises(FileExistsError):
        write_fork(graph(tmp_path), tmp_path, "u1", "s1")


def test_unknown_leaf_raises(tmp_path):
    write_session(tmp_path, "s1", [rec("u1", None)])
    with pytest.raises(KeyError):
        write_fork(graph(tmp_path), tmp_path, "nope")
