"""Summarise one branch so it can be sent into another."""
from __future__ import annotations

from .graph import ConvGraph, PromptNode

HEADER = "別の枝で次のことを試しました。この会話の内容と比較・統合してください。\n"


def _ancestry(n: PromptNode | None) -> list[PromptNode]:
    out = []
    while n is not None:
        out.append(n)
        n = n.parent
    return out  # self first, root last


def common_ancestor(a: PromptNode, b: PromptNode) -> PromptNode | None:
    seen = {id(x) for x in _ancestry(a)}
    return next((x for x in _ancestry(b) if id(x) in seen), None)


def merge_steps(graph: ConvGraph, a: PromptNode, b: PromptNode) -> list[tuple[str, str]]:
    """(prompt, result) from just below the common ancestor down to b inclusive."""
    ca = common_ancestor(a, b)
    path = []
    for x in _ancestry(b):
        if x is ca:
            break
        path.append(x)
    path.reverse()
    return [(x.text, graph.last_result(x.uuid)) for x in path]


def merge_text(graph: ConvGraph, a: PromptNode, b: PromptNode, max_result_chars: int = 1500) -> str:
    steps = merge_steps(graph, a, b)
    if not steps:
        return ""
    parts = [HEADER]
    for i, (prompt, result) in enumerate(steps, 1):
        if len(result) > max_result_chars:
            result = result[:max_result_chars] + "…（省略）"
        parts.append(f"## 指示 {i}\n{prompt}\n\n### 結果\n{result}\n")
    return "\n".join(parts)
