from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..errors import StageError


@dataclass
class WhisperResult:
    metadata: dict[str, Any]
    segments: list[dict[str, Any]]


def _normalize_device(device: str) -> str:
    if device != "auto":
        return device

    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _normalize_compute_type(device: str, compute_type: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


def transcribe_audio(
    audio_path: Path,
    *,
    config: dict[str, Any],
) -> WhisperResult:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise StageError(
            "未安装 faster-whisper。请先执行 `uv sync` 或 "
            "`uv pip install -e .`。"
        ) from exc

    model_name = str(config.get("model", "large-v3"))
    language = config.get("language")
    device = _normalize_device(str(config.get("device", "auto")))
    compute_type = _normalize_compute_type(
        device,
        str(config.get("compute_type", "auto")),
    )

    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        raise StageError(
            f"无法加载 Whisper 模型 {model_name!r} "
            f"(device={device}, compute_type={compute_type})。"
        ) from exc

    kwargs = {
        "language": language,
        "beam_size": int(config.get("beam_size", 5)),
        "vad_filter": bool(config.get("vad_filter", True)),
        "word_timestamps": bool(config.get("word_timestamps", False)),
        "condition_on_previous_text": bool(
            config.get("condition_on_previous_text", True)
        ),
    }

    try:
        segments_iter, info = model.transcribe(
            str(audio_path),
            **kwargs,
        )
    except Exception as exc:
        raise StageError("Whisper 转录执行失败。") from exc

    segments: list[dict[str, Any]] = []

    try:
        for i, seg in enumerate(segments_iter):
            text = (seg.text or "").strip()
            if not text:
                continue

            item: dict[str, Any] = {
                "id": f"tr_{i:06d}",
                "start": round(float(seg.start), 6),
                "end": round(float(seg.end), 6),
                "text": text,
            }

            avg_logprob = getattr(seg, "avg_logprob", None)
            no_speech_prob = getattr(seg, "no_speech_prob", None)

            if avg_logprob is not None:
                item["avg_logprob"] = round(float(avg_logprob), 6)
            if no_speech_prob is not None:
                item["no_speech_prob"] = round(float(no_speech_prob), 6)

            words = getattr(seg, "words", None)
            if words:
                item["words"] = [
                    {
                        "start": round(float(w.start), 6),
                        "end": round(float(w.end), 6),
                        "word": str(w.word),
                        "probability": (
                            round(float(w.probability), 6)
                            if getattr(w, "probability", None) is not None
                            else None
                        ),
                    }
                    for w in words
                ]

            segments.append(item)

    except Exception as exc:
        raise StageError("读取 Whisper 转录结果失败。") from exc

    metadata = {
        "model": model_name,
        "language_requested": language,
        "language_detected": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
        "device": device,
        "compute_type": compute_type,
        "beam_size": kwargs["beam_size"],
        "vad_filter": kwargs["vad_filter"],
        "word_timestamps": kwargs["word_timestamps"],
    }

    return WhisperResult(
        metadata=metadata,
        segments=segments,
    )
