from __future__ import annotations

import json
from typing import Any


def _size(item: Any) -> int:
    return len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))


def chunk_evidence(
    timeline: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0

    for item in timeline:
        item_size = _size(item)
        if current and current_size + item_size > max_chars:
            chunks.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item_size

    if current:
        chunks.append(current)
    return chunks
