"""Helpers for building synthetic Claude Code session records."""
import json
from pathlib import Path

_ts = [0]


def _next_ts() -> str:
    _ts[0] += 1
    s = _ts[0]
    return f"2026-11-10T{s // 3600 % 24:02d}:{s // 60 % 60:02d}:{s % 60:02d}.000Z"


def rec(uuid, parent, type="user", text=None, session="s1", **extra) -> dict:
    d = {"type": type, "uuid": uuid, "parentUuid": parent, "sessionId": session,
         "timestamp": extra.pop("timestamp", None) or _next_ts(), "isSidechain": False}
    if type == "user":
        d["message"] = {"role": "user", "content": text if text is not None else uuid}
        d["promptSource"] = "typed"
    elif type == "assistant":
        d["message"] = {"role": "assistant",
                        "content": [{"type": "text", "text": text if text is not None else uuid}]}
    d.update(extra)
    return d


def write_session(dir: Path, session_id: str, records: list[dict]) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    p = dir / f"{session_id}.jsonl"
    with p.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p
