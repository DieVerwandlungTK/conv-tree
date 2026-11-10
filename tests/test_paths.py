from pathlib import Path
from conv_tree.paths import project_slug, project_dir, sessions_dir


def test_project_slug():
    assert project_slug("/home/user.name/projects/conv-tree") == \
        "-home-user-name-projects-conv-tree"


def test_project_dir_and_sessions_dir(tmp_path):
    assert project_dir("/a/b", tmp_path) == tmp_path / "projects" / "-a-b"
    assert sessions_dir(tmp_path) == tmp_path / "sessions"
