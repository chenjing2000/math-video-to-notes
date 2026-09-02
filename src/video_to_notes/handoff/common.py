from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

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


def response_matches_request(
    path: Path,
    expected_request_id: str,
    *,
    validator: Callable[[dict[str, Any]], None] | None = None,
) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        data = read_json(path)
        if not isinstance(data, dict):
            return False
        if str(data.get("request_id", "")) != expected_request_id:
            return False
        if validator is not None:
            validator(data)
        return True
    except Exception:
        return False


def prepare_task_directories(
    tasks: Path,
    responses: Path,
    *,
    reusable: dict[str, tuple[str, Callable[[dict[str, Any]], None] | None]] | None = None,
) -> set[str]:
    """Reset task files while preserving only exact, valid response matches.

    reusable maps response filename -> (expected_request_id, optional validator).
    Returns the set of response filenames that were preserved.
    """
    reusable = reusable or {}
    preserved: dict[str, bytes] = {}
    for name, (rid, validator) in reusable.items():
        path = responses / name
        if response_matches_request(path, rid, validator=validator):
            preserved[name] = path.read_bytes()

    ensure_clean_dir(tasks)
    ensure_clean_dir(responses)
    for name, raw in preserved.items():
        target = responses / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return set(preserved)


def manifest_request_id(manifest: dict[str, Any], output_name: str) -> str:
    requests = manifest.get("requests", {})
    if isinstance(requests, dict):
        entry = requests.get(output_name, {})
        if isinstance(entry, dict):
            return str(entry.get("request_id", ""))
    return str(manifest.get("request_id", ""))


def response_is_ready(workspace_root: Path, stage: str, manifest: dict[str, Any], output_name: str) -> bool:
    expected = manifest_request_id(manifest, output_name)
    if not expected:
        return False
    return response_matches_request(response_root(workspace_root, stage) / output_name, expected)
