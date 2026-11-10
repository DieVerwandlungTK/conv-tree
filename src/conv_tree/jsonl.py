"""Incremental reader for append-only JSONL files."""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class JsonlTail:
    """Returns only the complete lines appended since the previous call."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.offset = 0

    def reset(self) -> None:
        self.offset = 0

    def read_new(self) -> list[dict]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:
            self.reset()
        if size == self.offset:
            return []
        with self.path.open("rb") as f:
            f.seek(self.offset)
            data = f.read(size - self.offset)
        end = data.rfind(b"\n")
        if end < 0:
            return []  # partial line only; wait for the writer to finish it
        self.offset += end + 1
        out = []
        for line in data[:end].split(b"\n"):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                log.warning("skipping invalid JSON line in %s", self.path)
        return out
