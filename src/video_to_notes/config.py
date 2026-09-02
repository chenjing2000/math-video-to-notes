from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from importlib.resources import files

import yaml

from .errors import ConfigError


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "workspace_root": "workspace",
        "copy_source_video": False,
    },
    "pipeline": {
        "stop_on_failure": True,
    },
    "logging": {
        "level": "INFO",
        "console": True,
        "file": True,
    },
    "codex": {
        "model_routing": {
            "reconstruction": "terra",
            "completion": "terra",
            "review": {
                "factual": "luna-high",
                "math": "sol",
                "pedagogical": "terra",
            },
        },
    },
    "llm": {
        "mode": "codex_handoff",
    },
    "performance": {
        "packet_warning_chars": {
            "reconstruction": 30000,
            "completion": 20000,
            "factual_review": 15000,
            "math_review": 20000,
            "pedagogical_review": 15000,
        },
    },
    "tools": {
        "ffmpeg": "auto",
        "ffprobe": "auto",
    },
    "visual": {
        "coverage_interval": 45.0,
        "extraction_width": 960,
        "jpeg_quality": 3,
        "scan": {
            "enabled": True,
            "interval": 2.0,
            "width": 640,
            "jpeg_quality": 6,
        },
        "scene": {
            "enabled": True,
            "threshold": 0.08,
            "min_gap_seconds": 0.75,
        },
        "transition": {
            "duplicate_change_ratio": 0.015,
            "duplicate_phash_distance": 5,
            "incremental_change_ratio": 0.24,
            "incremental_phash_distance": 24,
            "pixel_difference_threshold": 24,
        },
        "classification": {
            "progressive_min_incremental_events": 2,
            "dynamic_events_per_minute": 10.0,
            "dynamic_min_mean_change_ratio": 0.30,
        },
        "evidence": {
            "extraction_width": 1600,
            "jpeg_quality": 2,
            "stable_max_frames": 2,
            "progressive_max_frames": 8,
            "dynamic_max_frames": 10,
            "mixed_max_frames": 6,
        },
    },
    "transcription": {
        "audio": {
            "sample_rate": 16000,
            "channels": 1,
            "codec": "pcm_s16le",
        },
        "whisper": {
            "model": "large-v3",
            "language": "zh",
            "device": "auto",
            "compute_type": "auto",
            "beam_size": 5,
            "vad_filter": True,
            "word_timestamps": False,
            "condition_on_previous_text": True,
        },
        "output": {
            "write_json": True,
            "write_srt": True,
            "write_txt": True,
        },
    },
    "evidence": {
        "transcript_padding_before": 1.5,
        "transcript_padding_after": 1.5,
        "min_overlap_seconds": 0.05,
        "include_orphan_transcripts": True,
        "confidence": {
            "visual_weight": 0.55,
            "transcript_weight": 0.45,
        },
    },
    "reconstruction": {
        "prompts_file": "package:prompts.yaml",
        "max_evidence_chars_per_chunk": 28000,
        "infer_problem_figures": True,
        "max_figures_per_problem": 2,
        "llm": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model": "",
            "timeout_seconds": 180,
            "temperature": 0.0,
        },
    },
    "completion": {
        "prompts_file": "package:prompts.yaml",
        "max_items_per_call": 12,
        "reject_unreferenced_targets": True,
        "llm": {
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "model": "",
            "timeout_seconds": 180,
            "temperature": 0.0,
        },
    },
    "review": {
        "prompts_file": "package:prompts.yaml",
        "reject_unreferenced_targets": True,
        "factual": {
            "enabled": True,
            "trigger_statuses": ["probable", "uncertain", "conflict"],
            "always_review_problem_fields": ["statement", "teacher_solution", "teacher_answer"],
            "llm": {
                "provider": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "model": "",
                "timeout_seconds": 180,
                "temperature": 0.0,
            },
        },
        "math": {
            "enabled": True,
            "review_all_problems": True,
            "llm": {
                "provider": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "model": "",
                "timeout_seconds": 180,
                "temperature": 0.0,
            },
        },
        "pedagogical": {
            "enabled": True,
            "whole_lecture": True,
            "llm": {
                "provider": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "model": "",
                "timeout_seconds": 180,
                "temperature": 0.0,
            },
        },
    },
    "render": {
        "template": "package:lecture.tex.j2",
        "engine": "xelatex",
        "runs": 2,
        "timeout_seconds": 180,
        "interaction": "nonstopmode",
        "halt_on_error": True,
        "copy_publication_images": True,
        "fail_on_missing_image": True,
        "fail_on_missing_character": True,
    },
    "audit": {
        "fail_on_warning": False,
        "require_rendered_stage": True,
        "require_xelatex_runs": 2,
        "block_open_possible_teacher_error": True,
        "block_open_review_error": True,
    },
    "stages": {
        "visual": {"enabled": True},
        "transcription": {"enabled": True},
        "evidence": {"enabled": True},
        "reconstruction": {"enabled": True},
        "completion": {"enabled": True},
        "review": {"enabled": True},
        "render": {"enabled": True},
        "audit": {"enabled": True},
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
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


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        resource = package_resource_path("default.yaml")
        if resource.exists():
            data = yaml.safe_load(resource.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                return _deep_merge(DEFAULT_CONFIG, data)
        return deepcopy(DEFAULT_CONFIG)

    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ConfigError(f"无法读取配置文件: {config_path}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点必须是 mapping/object。")

    return _deep_merge(DEFAULT_CONFIG, data)
