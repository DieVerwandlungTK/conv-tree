"""Locations of Claude Code data."""
import re
from pathlib import Path

DEFAULT_CLAUDE_HOME = Path.home() / ".claude"


def project_slug(cwd: str) -> str:
    """Claude Code's directory name for a project cwd."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def project_dir(cwd: str, claude_home: Path = DEFAULT_CLAUDE_HOME) -> Path:
    return Path(claude_home) / "projects" / project_slug(cwd)


def sessions_dir(claude_home: Path = DEFAULT_CLAUDE_HOME) -> Path:
    return Path(claude_home) / "sessions"
