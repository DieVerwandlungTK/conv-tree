import json
from factory import rec, write_session
from conv_tree.app import ConvTreeApp, MergeScreen
from conv_tree.herdr import Herdr

CWD = "/proj"


class FakeRunner:
    def __init__(self, pid_session=None, status="idle"):
        self.calls = []
        self.status = status

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["agent", "list"]:
            return {"result": {"agents": [{"agent": "claude", "pane_id": "w:p1", "cwd": CWD, "focused": True,
                                           "agent_status": self.status}]}}
        if args[:2] == ["pane", "process-info"]:
            return {"result": {"process_info": {"foreground_processes": [{"pid": 11}]}}}
        if args[:2] == ["pane", "split"]:
            return {"result": {"pane": {"pane_id": "w:new"}}}
        return {}

    def did(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


def home(tmp_path):
    h = tmp_path / "claude"
    proj = h / "projects" / "-proj"
    write_session(proj, "s1", [rec("u1", None, text="first prompt"), rec("a1", "u1", "assistant", text="answer one"),
                               rec("u2", "a1", text="second prompt"), rec("a2", "u2", "assistant"),
                               rec("u3", "a1", text="third prompt"), rec("a3", "u3", "assistant")])
    (h / "sessions").mkdir()
    (h / "sessions" / "11.json").write_text(json.dumps({"sessionId": "s1"}))
    return h, proj


def labels(app):
    out = []

    def walk(n):
        for c in n.children:
            out.append(str(c.label))
            walk(c)
    walk(app.query_one("#tree").root)
    return out


async def select(app, pilot, uuid):
    app.select_uuid(uuid)
    await pilot.pause()


async def test_renders_forest_and_marker(tmp_path):
    h, _ = home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        ls = labels(app)
        assert any("first prompt" in l for l in ls)
        assert any("second prompt" in l for l in ls)
        third = next(l for l in ls if "third prompt" in l)
        assert third.startswith("▶")  # last appended record in s1 is a3 → u3


async def test_detail_shows_result(tmp_path):
    h, _ = home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await select(app, pilot, "u1")
        assert "answer one" in str(app.query_one("#detail").render())


async def test_fork_key_calls_fork_here(tmp_path):
    h, _ = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await select(app, pilot, "u2")
        await pilot.press("f")
        await pilot.pause(0.3)
        assert r.did("pane", "split", "w:p1")
        assert r.did("agent", "start")
        assert r.did("pane", "send-text", "w:new", "\x1b[200~second prompt\x1b[201~")


async def _merge(pilot, app, source, dest):
    await select(app, pilot, source)
    await pilot.press("b")
    await select(app, pilot, dest)
    await pilot.press("m")
    await pilot.pause()
    assert isinstance(app.screen, MergeScreen)


async def test_merge_defaults_to_direct_send(tmp_path):
    h, _ = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await _merge(pilot, app, "u2", "u3")  # u3 is where idle pane w:p1 sits
        assert "second prompt" in app.screen.query_one("TextArea").text
        assert "w:p1" in str(app.screen.query_one("#merge-mode").render())
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        prompts = r.did("agent", "prompt")
        assert prompts and prompts[0][2] == "w:p1" and "second prompt" in prompts[0][3]
        assert not r.did("pane", "split")


async def test_merge_toggle_to_new_fork(tmp_path):
    h, _ = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await _merge(pilot, app, "u2", "u3")
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert "new pane" in str(app.screen.query_one("#merge-mode").render())
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert r.did("pane", "split", "w:p1")
        prompts = r.did("agent", "prompt")
        assert prompts and prompts[0][2] != "w:p1"


async def test_merge_busy_pane_uses_fork(tmp_path):
    h, _ = home(tmp_path)
    r = FakeRunner(status="working")
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await _merge(pilot, app, "u2", "u3")
        assert "new pane" in str(app.screen.query_one("#merge-mode").render())
        await pilot.press("ctrl+o")  # direct is unavailable: stays on fork
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert r.did("pane", "split", "w:p1")


async def test_merge_into_mid_history_uses_fork(tmp_path):
    h, _ = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await _merge(pilot, app, "u3", "u2")  # no pane sits at u2
        assert "new pane" in str(app.screen.query_one("#merge-mode").render())
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert r.did("pane", "split", "w:p1")


async def test_merge_without_source_notifies(tmp_path):
    h, _ = home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await pilot.press("m")
        await pilot.pause()
        assert not isinstance(app.screen, MergeScreen)


async def test_poll_picks_up_new_prompt(tmp_path):
    h, proj = home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        write_session(proj, "s1", [rec("u9", "a3", text="brand new prompt")])
        await pilot.pause(0.5)
        assert any("brand new prompt" in l for l in labels(app))


async def test_linear_chain_is_flat(tmp_path):
    h = tmp_path / "claude"
    proj = h / "projects" / "-proj"
    recs, parent = [], None
    for i in range(50):
        recs += [rec(f"u{i}", parent, text=f"p{i}"), rec(f"a{i}", f"u{i}", "assistant")]
        parent = f"a{i}"
    write_session(proj, "s1", recs)
    (h / "sessions").mkdir(parents=True)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        tree = app.query_one("#tree")
        assert len(tree.root.children) == 50  # all at top level, no nesting


async def test_slow_herdr_does_not_pile_up_polls(tmp_path):
    import threading, time
    h, _ = home(tmp_path)
    state = {"live": 0, "max": 0}
    lock = threading.Lock()

    def slow(args):
        with lock:
            state["live"] += 1
            state["max"] = max(state["max"], state["live"])
        time.sleep(0.3)
        with lock:
            state["live"] -= 1
        return {}
    app = ConvTreeApp(CWD, Herdr(slow), h, poll_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.pause(1.0)
    assert state["max"] == 1


def chain_home(tmp_path):
    """p0 → p1 → … → p5 ─┬→ x0 → x1 → x2 → x3
                         └→ y0 → y1 → y2   (y2 is the last record → ▶)"""
    h = tmp_path / "claude"
    proj = h / "projects" / "-proj"
    recs, parent = [], None

    def chain(prefix, n, parent):
        for i in range(n):
            recs.extend([rec(f"{prefix}{i}", parent, text=f"{prefix}{i}"),
                         rec(f"a{prefix}{i}", f"{prefix}{i}", "assistant")])
            parent = f"a{prefix}{i}"
        return parent

    fork = chain("p", 6, None)
    chain("x", 4, fork)
    chain("y", 3, fork)
    write_session(proj, "s1", recs)
    (h / "sessions").mkdir(parents=True)
    (h / "sessions" / "11.json").write_text(json.dumps({"sessionId": "s1"}))
    return h


async def test_branches_only_toggle(tmp_path):
    h = chain_home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        assert len(labels(app)) == 13
        await pilot.press("s")
        await pilot.pause()
        ls = labels(app)
        texts = [l for l in ls if not l.lstrip().startswith("…")]
        # root, branch point, branch heads, leaves (y2 also carries ▶)
        for want in ["p0", "p5", "x0", "x3", "y0", "y2"]:
            assert any(f" {want} " in f" {t} " or t.lstrip("▶▷◆ ").startswith(want) for t in texts), (want, ls)
        for hidden in ["p1", "p4", "x1", "x2", "y1"]:
            assert not any(t.lstrip("▶▷◆ ").startswith(hidden) for t in texts), (hidden, ls)
        gaps = [l.strip() for l in ls if l.lstrip().startswith("…")]
        assert "… 4 more" in gaps and "… 2 more" in gaps and "… 1 more" in gaps
        await pilot.press("s")
        await pilot.pause()
        assert len(labels(app)) == 13


async def test_branches_only_keeps_marked_nodes(tmp_path):
    h = chain_home(tmp_path)
    app = ConvTreeApp(CWD, Herdr(FakeRunner()), h, poll_interval=0.1, branches_only=True)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        assert any(l.startswith("▶") and "y2" in l for l in labels(app))
        app.merge_source = "p2"
        app._dirty = True
        app._apply(app.panes)
        await pilot.pause()
        assert any(l.startswith("◆") and "p2" in l for l in labels(app))


async def test_open_focuses_pane_already_there(tmp_path):
    h, proj = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await select(app, pilot, "u3")  # pane w:p1 (session s1) sits here
        await pilot.press("o")
        await pilot.pause(0.3)
        assert r.did("agent", "focus", "w:p1")
        assert not r.did("pane", "split")


async def test_open_resumes_session_ending_there(tmp_path):
    h, proj = home(tmp_path)
    write_session(proj, "s2", [rec("u1", None, session="s2"), rec("a1", "u1", "assistant", session="s2"),
                               rec("u2", "a1", session="s2"), rec("a2", "u2", "assistant", session="s2")])
    before = sorted(p.name for p in proj.iterdir())
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await select(app, pilot, "u2")
        await pilot.press("o")
        await pilot.pause(0.3)
        starts = r.did("agent", "start")
        assert starts and starts[0][-2:] == ["--resume", "s2"]
        assert r.did("agent", "rename", "w:new", "--clear")
        assert not r.did("pane", "send-text") and not r.did("agent", "prompt")
    assert sorted(p.name for p in proj.iterdir()) == before


async def test_open_mid_history_forks_including_result(tmp_path):
    h, proj = home(tmp_path)
    r = FakeRunner()
    app = ConvTreeApp(CWD, Herdr(r), h, poll_interval=0.1)
    async with app.run_test() as pilot:
        await pilot.pause(0.3)
        await select(app, pilot, "u1")
        await pilot.press("o")
        await pilot.pause(0.3)
        starts = r.did("agent", "start")
        assert starts
        sid = starts[0][-1]
        assert sid != "s1"
        uuids = [json.loads(l)["uuid"] for l in (proj / f"{sid}.jsonl").read_text().splitlines()]
        assert uuids == ["u1", "a1"]
        assert not r.did("pane", "send-text") and not r.did("agent", "prompt")
