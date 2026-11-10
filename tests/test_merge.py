from factory import rec, write_session
from conv_tree.graph import ConvGraph
from conv_tree.merge import common_ancestor, merge_steps, merge_text


def setup(tmp_path, long=False):
    # u1 -> {u2 -> u4, u3}; plus unrelated root z1
    write_session(tmp_path, "s1", [
        rec("u1", None), rec("a1", "u1", "assistant", text="r1"),
        rec("u2", "a1"), rec("a2", "u2", "assistant", text="r2" * (2500 if long else 1)),
        rec("u4", "a2"), rec("a4", "u4", "assistant", text="r4"),
        rec("u3", "a1"), rec("a3", "u3", "assistant", text="r3"),
        rec("z1", None, session="s9"), rec("y1", "z1", "assistant", text="rz", session="s9"),
    ])
    g = ConvGraph(tmp_path)
    g.refresh()
    nodes = {}

    def walk(ns):
        for n in ns:
            nodes[n.uuid] = n
            walk(n.children)
    walk(g.forest())
    return g, nodes


def test_common_ancestor_siblings(tmp_path):
    _, n = setup(tmp_path)
    assert common_ancestor(n["u2"], n["u3"]) is n["u1"]
    assert common_ancestor(n["u4"], n["z1"]) is None


def test_merge_steps_from_branch_point(tmp_path):
    g, n = setup(tmp_path)
    assert merge_steps(g, n["u3"], n["u4"]) == [("u2", "r2"), ("u4", "r4")]


def test_merge_steps_unrelated(tmp_path):
    g, n = setup(tmp_path)
    assert merge_steps(g, n["u3"], n["z1"]) == [("z1", "rz")]


def test_a_descendant_of_b(tmp_path):
    g, n = setup(tmp_path)
    assert merge_steps(g, n["u4"], n["u2"]) == []
    assert merge_text(g, n["u4"], n["u2"]) == ""


def test_merge_text_format(tmp_path):
    g, n = setup(tmp_path)
    assert merge_text(g, n["u3"], n["u4"]) == (
        "別の枝で次のことを試しました。この会話の内容と比較・統合してください。\n\n"
        "## 指示 1\nu2\n\n### 結果\nr2\n\n"
        "## 指示 2\nu4\n\n### 結果\nr4\n"
    )


def test_merge_text_truncates(tmp_path):
    g, n = setup(tmp_path, long=True)
    t = merge_text(g, n["u3"], n["u2"])
    assert ("r2" * 750 + "…（省略）") in t
    assert "r2" * 751 not in t
