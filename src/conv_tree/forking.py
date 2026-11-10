"""Write a new Claude Code session file that ends at a chosen record."""
from __future__ import annotations

import json
import os
import tempfile
import uuid as uuidlib
from pathlib import Path

from .graph import ConvGraph


def _is_boundary(raw: dict) -> bool:
    return raw.get("type") == "system" and raw.get("subtype") == "compact_boundary"


def write_fork(graph: ConvGraph, project_dir: Path, leaf_uuid: str,
               new_session_id: str | None = None) -> str:
    """Copy the root→leaf path (from the last compaction boundary) into <new id>.jsonl.

    Existing files are never modified; an existing target raises FileExistsError.
    """
    if leaf_uuid not in graph.records:
        raise KeyError(leaf_uuid)
    path = graph.path_to_root(leaf_uuid)
    for i in range(len(path) - 1, -1, -1):
        if _is_boundary(path[i].raw):
            path = path[i:]
            break
    sid = new_session_id or str(uuidlib.uuid4())
    project_dir = Path(project_dir)
    target = project_dir / f"{sid}.jsonl"
    fd, tmp = tempfile.mkstemp(dir=project_dir, prefix=".conv-tree-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for r in path:
                f.write(json.dumps(dict(r.raw, sessionId=sid), ensure_ascii=False) + "\n")
        os.link(tmp, target)  # fails if target exists: never clobber
    finally:
        os.unlink(tmp)
    return sid
