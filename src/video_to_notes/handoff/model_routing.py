from __future__ import annotations

from typing import Any

from ..errors import StageError

DEFAULT_MODEL_ROUTING: dict[str, Any] = {
    "reconstruction": "terra",
    "completion": "terra",
    "review": {
        "factual": "luna-high",
        "math": "sol",
        "pedagogical": "terra",
    },
}

_ALLOWED_MODELS = {"luna-high", "terra", "sol"}


def _normalize_model(value: Any) -> str:
    model = str(value or "").strip().lower()
    aliases = {
        "luna high": "luna-high",
        "luna_high": "luna-high",
    }
    return aliases.get(model, model)


def resolve_required_model(config: dict[str, Any], task_type: str) -> str:
    routing = config.get("codex", {}).get("model_routing", {})

    if task_type in {"reconstruction", "completion"}:
        raw = routing.get(task_type, DEFAULT_MODEL_ROUTING[task_type])
    elif task_type in {"factual", "math", "pedagogical"}:
        review_cfg = routing.get("review", {})
        default_review = DEFAULT_MODEL_ROUTING["review"]
        raw = review_cfg.get(task_type, default_review[task_type])
    else:
        raise StageError(f"未知 Codex task_type: {task_type}")

    model = _normalize_model(raw)

    # Luna may never be routed below Luna High.
    if model.startswith("luna") and model != "luna-high":
        raise StageError(
            f"Codex model routing 非法: {task_type} -> {raw!r}。"
            "Luna 路由最低必须使用 luna-high。"
        )

    if model not in _ALLOWED_MODELS:
        raise StageError(
            f"Codex model routing 非法: {task_type} -> {raw!r}。"
            f"当前允许模型: {sorted(_ALLOWED_MODELS)}"
        )

    return model


def resolved_model_routing(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "reconstruction": resolve_required_model(config, "reconstruction"),
        "completion": resolve_required_model(config, "completion"),
        "review": {
            "factual": resolve_required_model(config, "factual"),
            "math": resolve_required_model(config, "math"),
            "pedagogical": resolve_required_model(config, "pedagogical"),
        },
    }
