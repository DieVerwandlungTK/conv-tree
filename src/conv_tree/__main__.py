import argparse
import os
from pathlib import Path

from .app import ConvTreeApp
from .paths import DEFAULT_CLAUDE_HOME


def main() -> None:
    ap = argparse.ArgumentParser(prog="conv-tree", description="Claude Code conversation tree for herdr")
    ap.add_argument("--cwd", default=os.getcwd(), help="project directory (default: current directory)")
    ap.add_argument("--claude-home", type=Path, default=DEFAULT_CLAUDE_HOME)
    ap.add_argument("--branches-only", action="store_true",
                    help="start by showing only branch points, branch heads, leaves and marked prompts (toggle: s)")
    args = ap.parse_args()
    ConvTreeApp(os.path.abspath(args.cwd), claude_home=args.claude_home, branches_only=args.branches_only).run()


if __name__ == "__main__":
    main()
