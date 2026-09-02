from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..errors import ConfigError


def load_prompts(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Prompt 配置不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("prompts.yaml 根节点必须是 mapping/object。")
    return data


def render(template: str, marker: str, value: str) -> str:
    token = "{{" + marker + "}}"
    if token not in template:
        raise ConfigError(f"Prompt 模板缺少占位符: {token}")
    return template.replace(token, value)
