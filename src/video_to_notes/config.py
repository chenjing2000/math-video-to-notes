from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def package_resource_path(name: str) -> Path:
    return Path(str(files("video_to_notes.resources").joinpath(name)))


def resolve_resource_path(value: str | Path, *, default_name: str | None = None) -> Path:
    text = str(value)
    if text.startswith("package:"):
        return package_resource_path(text.split(":", 1)[1])
    path = Path(text).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidate = Path.cwd() / path
    if candidate.exists():
        return candidate.resolve()
    if default_name:
        return package_resource_path(default_name)
    return candidate.resolve()


def _load_packaged_defaults() -> dict[str, Any]:
    resource = package_resource_path("default.yaml")
    if not resource.exists():
        raise ConfigError(f"缺少内置默认配置: {resource}")
    try:
        data = yaml.safe_load(resource.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"无法读取内置默认配置: {resource}") from exc
    if not isinstance(data, dict):
        raise ConfigError("内置 default.yaml 根节点必须是 mapping/object。")
    return data


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the packaged defaults and optionally deep-merge a user config.

    `resources/default.yaml` is the single authoritative source of defaults.  Keeping
    the defaults out of Python prevents configuration drift between two copies.
    """
    defaults = _load_packaged_defaults()
    if path is None:
        return deepcopy(defaults)

    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"无法读取配置文件: {config_path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是 mapping/object。")

    return _deep_merge(defaults, data)
