"""Union of all session files in a project, viewed as a tree of user prompts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .jsonl import JsonlTail

_NOT_PROMPT_PREFIXES = ("<", "This session is being continued", "[Request interrupted")


@dataclass(eq=False)
class Record:
    uuid: str
    parent: str | None
    type: str
    timestamp: str
    sessions: set[str]
    raw: dict


@dataclass(eq=False)
class PromptNode:
    uuid: str
    text: str
    timestamp: str
    sessions: set[str]
    parent: PromptNode | None = None
    children: list[PromptNode] = field(default_factory=list)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif b.get("type") == "image":
                parts.append("[image]")
        return " ".join(p for p in parts if p)
    return ""


def prompt_text(raw: dict) -> str:
    return _content_text((raw.get("message") or {}).get("content")).strip()


def is_prompt(raw: dict) -> bool:
    if raw.get("type") != "user":
        return False
    if raw.get("isMeta") or "toolUseResult" in raw or raw.get("isCompactSummary") or raw.get("isSidechain"):
        return False
    if "promptSource" in raw:
        return raw["promptSource"] != "system"
    content = (raw.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = prompt_text(raw)
    return bool(text) and not text.startswith(_NOT_PROMPT_PREFIXES)


class ConvGraph:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.records: dict[str, Record] = {}
        self.last_uuid_by_session: dict[str, str] = {}
        self._tails: dict[Path, JsonlTail] = {}
        self._prompt_of: dict[str, str | None] = {}

    # -- loading -------------------------------------------------------
    def refresh(self) -> bool:
        changed = False
        if self.project_dir.is_dir():
            for path in sorted(self.project_dir.glob("*.jsonl")):
                tail = self._tails.setdefault(path, JsonlTail(path))
                for raw in tail.read_new():
                    changed |= self._add(raw, path.stem)
        if changed:
            self._prompt_of.clear()
        return changed

    def _add(self, raw: dict, file_session: str) -> bool:
        uuid = raw.get("uuid")
        if not uuid:
            return False
        session = raw.get("sessionId") or file_session
        self.last_uuid_by_session[session] = uuid
        r = self.records.get(uuid)
        if r is not None:
            r.sessions.add(session)
            return True
        self.records[uuid] = Record(
            uuid=uuid,
            parent=raw.get("parentUuid") or raw.get("logicalParentUuid"),
            type=raw.get("type", ""),
            timestamp=raw.get("timestamp") or "",
            sessions={session},
            raw=raw,
        )
        return True

    # -- queries -------------------------------------------------------
    def prompt_of(self, uuid: str | None) -> str | None:
        """uuid of the nearest prompt record at or above `uuid`."""
        path, seen, cur, found = [], set(), uuid, None
        while cur is not None and cur not in seen:
            if cur in self._prompt_of:
                found = self._prompt_of[cur]
                break
            r = self.records.get(cur)
            if r is None:
                break
            seen.add(cur)
            path.append(cur)
            if is_prompt(r.raw):
                found = cur
                break
            cur = r.parent
        for u in path:
            self._prompt_of[u] = found
        return found

    def path_to_root(self, uuid: str) -> list[Record]:
        out, seen, cur = [], set(), uuid
        while cur is not None and cur not in seen and cur in self.records:
            seen.add(cur)
            r = self.records[cur]
            out.append(r)
            cur = r.parent
        out.reverse()
        return out

    def _owned(self, prompt_uuid: str) -> list[Record]:
        return [r for r in self.records.values() if self.prompt_of(r.uuid) == prompt_uuid]

    def last_record_under(self, prompt_uuid: str) -> str:
        owned = self._owned(prompt_uuid)
        return max(owned, key=lambda r: r.timestamp).uuid if owned else prompt_uuid

    def last_result(self, prompt_uuid: str) -> str:
        best = None
        for r in self._owned(prompt_uuid):
            if r.type != "assistant":
                continue
            text = _content_text((r.raw.get("message") or {}).get("content")).strip()
            if text and (best is None or r.timestamp >= best[0]):
                best = (r.timestamp, text)
        return best[1] if best else ""

    def sessions_ending_at(self, prompt_uuid: str) -> list[str]:
        """Sessions whose latest record belongs to `prompt_uuid`, most recently written first."""
        hits = [(self.records[leaf].timestamp, sid) for sid, leaf in self.last_uuid_by_session.items()
                if leaf in self.records and self.prompt_of(leaf) == prompt_uuid]
        return [sid for _, sid in sorted(hits, reverse=True)]

    def forest(self) -> list[PromptNode]:
        nodes: dict[str, PromptNode] = {}
        latest: dict[str, str] = {}
        for r in self.records.values():
            if is_prompt(r.raw):
                nodes[r.uuid] = PromptNode(r.uuid, prompt_text(r.raw), r.timestamp, r.sessions)
        for r in self.records.values():
            p = self.prompt_of(r.uuid)
            if p is not None and r.timestamp > latest.get(p, ""):
                latest[p] = r.timestamp
        roots = []
        for uuid, node in nodes.items():
            parent = self.prompt_of(self.records[uuid].parent)
            if parent is not None and parent in nodes:
                node.parent = nodes[parent]
                nodes[parent].children.append(node)
            else:
                roots.append(node)
        # propagate subtree-latest timestamps upward, deepest first
        depth: dict[str, int] = {}
        for node in nodes.values():
            chain, cur = [], node
            while cur is not None and cur.uuid not in depth:
                chain.append(cur)
                cur = cur.parent
            start = depth[cur.uuid] + 1 if cur is not None else 0
            for i, n in enumerate(reversed(chain)):
                depth[n.uuid] = start + i
        for node in sorted(nodes.values(), key=lambda n: -depth[n.uuid]):
            node.children.sort(key=lambda n: n.timestamp)
            if node.parent is not None:
                pl = latest.get(node.parent.uuid, "")
                latest[node.parent.uuid] = max(pl, latest.get(node.uuid, node.timestamp))
        roots.sort(key=lambda n: latest.get(n.uuid, n.timestamp), reverse=True)
        return roots
