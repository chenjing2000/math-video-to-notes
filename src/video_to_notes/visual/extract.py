from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ..errors import StageError
from ..util import atomic_write_json


_SHOWINFO_RE = re.compile(r"\bpts_time:([0-9]+(?:\.[0-9]+)?)")


def _clear_jpegs(directory: Path, prefix: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for p in directory.glob(f"{prefix}_*.jpg"):
        p.unlink()


def _extract_interval_frames(
    *,
    video_path: Path,
    ffmpeg: Path,
    output_dir: Path,
    prefix: str,
    duration: float,
    interval: float,
    width: int,
    jpeg_quality: int,
    json_name: str,
    source: str,
) -> list[dict[str, Any]]:
    if interval <= 0:
        raise StageError(f"{source} interval 必须大于 0。")

    _clear_jpegs(output_dir, prefix)
    pattern = output_dir / f"{prefix}_%06d.jpg"
    vf = f"fps=1/{interval},scale={width}:-2"

    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-q:v", str(jpeg_quality),
        "-start_number", "0",
        str(pattern),
        "-y",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise StageError(
            f"{source} 抽帧失败："
            + (proc.stderr.strip() or f"exit={proc.returncode}")
        )

    paths = sorted(output_dir.glob(f"{prefix}_*.jpg"))
    frames: list[dict[str, Any]] = []
    for i, path in enumerate(paths):
        t = min(float(i) * interval, max(0.0, duration))
        frames.append({
            "id": f"{prefix}_{i:06d}",
            "time": round(t, 6),
            "path": str(path),
            "source": source,
        })

    if not frames:
        raise StageError(f"{source} 抽帧没有产生任何图像。")

    atomic_write_json(output_dir / json_name, {
        "schema_version": "1.0",
        "interval": interval,
        "frames": frames,
    })
    return frames


def extract_coverage_frames(
    *,
    video_path: Path,
    ffmpeg: Path,
    output_dir: Path,
    duration: float,
    interval: float,
    width: int,
    jpeg_quality: int,
) -> list[dict[str, Any]]:
    return _extract_interval_frames(
        video_path=video_path,
        ffmpeg=ffmpeg,
        output_dir=output_dir,
        prefix="coverage",
        duration=duration,
        interval=interval,
        width=width,
        jpeg_quality=jpeg_quality,
        json_name="coverage.json",
        source="coverage",
    )


def extract_scan_frames(
    *,
    video_path: Path,
    ffmpeg: Path,
    output_dir: Path,
    duration: float,
    interval: float,
    width: int,
    jpeg_quality: int,
) -> list[dict[str, Any]]:
    return _extract_interval_frames(
        video_path=video_path,
        ffmpeg=ffmpeg,
        output_dir=output_dir,
        prefix="scan",
        duration=duration,
        interval=interval,
        width=width,
        jpeg_quality=jpeg_quality,
        json_name="scan.json",
        source="scan",
    )


def extract_scene_frames(
    *,
    video_path: Path,
    ffmpeg: Path,
    output_dir: Path,
    threshold: float,
    min_gap_seconds: float,
    width: int,
    jpeg_quality: int,
) -> list[dict[str, Any]]:
    _clear_jpegs(output_dir, "scene")

    if threshold <= 0 or threshold >= 1:
        raise StageError("visual.scene.threshold 必须位于 (0, 1) 之间。")

    pattern = output_dir / "scene_%06d.jpg"
    vf = f"select='gt(scene,{threshold})',scale={width}:-2,showinfo"

    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel", "info",
        "-i", str(video_path),
        "-vf", vf,
        "-fps_mode", "vfr",
        "-q:v", str(jpeg_quality),
        "-start_number", "0",
        str(pattern),
        "-y",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise StageError(
            "Scene change 抽帧失败："
            + (proc.stderr.strip() or f"exit={proc.returncode}")
        )

    times = [float(x) for x in _SHOWINFO_RE.findall(proc.stderr)]
    paths = sorted(output_dir.glob("scene_*.jpg"))

    count = min(len(times), len(paths))
    events: list[dict[str, Any]] = []
    last_time: float | None = None

    for i in range(count):
        t = times[i]
        if last_time is not None and (t - last_time) < min_gap_seconds:
            paths[i].unlink(missing_ok=True)
            continue
        events.append({
            "id": f"scn_{len(events):06d}",
            "time": round(t, 6),
            "path": str(paths[i]),
            "source": "scene",
        })
        last_time = t

    used = {Path(e["path"]).resolve() for e in events}
    for path in paths:
        if path.exists() and path.resolve() not in used:
            path.unlink()

    atomic_write_json(output_dir / "scene_events.json", {
        "schema_version": "1.0",
        "threshold": threshold,
        "min_gap_seconds": min_gap_seconds,
        "events": events,
    })
    return events


def extract_exact_frame(
    *,
    video_path: Path,
    ffmpeg: Path,
    time_seconds: float,
    output_path: Path,
    width: int,
    jpeg_quality: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel", "error",
        "-ss", f"{max(0.0, time_seconds):.6f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", str(jpeg_quality),
        str(output_path),
        "-y",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0 or not output_path.exists():
        raise StageError(
            f"提取 Evidence Frame 失败 @ {time_seconds:.3f}s："
            + (proc.stderr.strip() or f"exit={proc.returncode}")
        )
