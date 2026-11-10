from conv_tree.jsonl import JsonlTail


def test_read_new_incremental(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a":1}\n{"a":2}\n')
    t = JsonlTail(p)
    assert t.read_new() == [{"a": 1}, {"a": 2}]
    with p.open("a") as f:
        f.write('{"a":3}\n')
    assert t.read_new() == [{"a": 3}]


def test_partial_line_deferred(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a": 1')
    t = JsonlTail(p)
    assert t.read_new() == []
    with p.open("a") as f:
        f.write('}\n')
    assert t.read_new() == [{"a": 1}]


def test_invalid_line_skipped(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('not json\n{"b":2}\n')
    assert JsonlTail(p).read_new() == [{"b": 2}]


def test_truncated_file_resets(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"a":1}\n{"a":2}\n')
    t = JsonlTail(p)
    t.read_new()
    p.write_text('{"c":1}\n')
    assert t.read_new() == [{"c": 1}]


def test_missing_file_is_empty(tmp_path):
    assert JsonlTail(tmp_path / "nope.jsonl").read_new() == []
