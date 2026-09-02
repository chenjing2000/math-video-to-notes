from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..util import atomic_write_json, read_json


def task_root(workspace_root: Path, stage: str) -> Path:
    return workspace_root / "tasks" / stage


def response_root(workspace_root: Path, stage: str) -> Path:
    return workspace_root / "responses" / stage


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
    path.mkdir(parents=True, exist_ok=True)


def write_task_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)


def load_response(path: Path, description: str) -> dict[str, Any]:
    if not path.exists():
        raise StageError(
            f"缺少 Codex 响应文件: {path}。请先让 Codex 完成 {description} 任务。"
        )
    data = read_json(path)
    if not isinstance(data, dict):
        raise StageError(f"{description} 响应根节点必须为 object: {path}")
    return data


def write_instructions(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def require_request_id(data: dict[str, Any], expected: str, description: str) -> None:
    actual = str(data.get("request_id", ""))
    if actual != expected:
        raise StageError(
            f"{description} request_id 不匹配。expected={expected} actual={actual or '<missing>'}"
        )
