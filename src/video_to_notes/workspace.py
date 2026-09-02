from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import WorkspaceError
from .util import atomic_write_json, read_json, sha256_file, slugify_filename


@dataclass(frozen=True)
class Workspace:
    root: Path
    source: Path
    visual: Path
    transcript: Path
    evidence: Path
    lecture: Path
    review: Path
    images: Path
    latex: Path
    output: Path
    reports: Path
    logs: Path
    stages: Path
    project_file: Path

    @classmethod
    def from_root(cls, root: Path) -> "Workspace":
        return cls(
            root=root,
            source=root / "source",
            visual=root / "visual",
            transcript=root / "transcript",
            evidence=root / "evidence",
            lecture=root / "lecture",
            review=root / "review",
            images=root / "images",
            latex=root / "latex",
            output=root / "output",
            reports=root / "reports",
            logs=root / "logs",
            stages=root / "stages",
            project_file=root / "project.json",
        )


def _source_sha(video_path: Path, project_file: Path | None = None) -> str:
    stat = video_path.stat()
    if project_file and project_file.exists():
        try:
            old = read_json(project_file).get("source", {})
            if (
                str(old.get("original_path", "")) == str(video_path)
                and int(old.get("size_bytes", -1)) == stat.st_size
                and int(old.get("mtime_ns", -1)) == stat.st_mtime_ns
                and old.get("sha256")
            ):
                return str(old["sha256"])
        except Exception:
            pass
    return sha256_file(video_path)


def resolve_workspace_root(video_path: Path, workspace_root: Path) -> Path:
    base = workspace_root / slugify_filename(video_path.name)
    if not base.exists() or not (base / "project.json").exists():
        return base
    try:
        project = read_json(base / "project.json")
        source = project.get("source", {})
        if str(source.get("original_path", "")) == str(video_path.expanduser().resolve()):
            return base
        existing_sha = str(source.get("sha256", ""))
        current_sha = _source_sha(video_path.expanduser().resolve())
        if existing_sha and existing_sha == current_sha:
            return base
        return workspace_root / f"{base.name}__{current_sha[:8]}"
    except Exception:
        return base


def create_workspace(video_path: Path, *, workspace_root: Path, copy_source_video: bool = False) -> Workspace:
    video_path = video_path.expanduser().resolve()
    if not video_path.exists():
        raise WorkspaceError(f"输入视频不存在: {video_path}")
    if not video_path.is_file():
        raise WorkspaceError(f"输入路径不是文件: {video_path}")

    root = resolve_workspace_root(video_path, workspace_root)
    ws = Workspace.from_root(root)
    dirs = [
        ws.source, ws.visual / "coverage", ws.visual / "scan", ws.visual / "scene",
        ws.visual / "segments", ws.visual / "evidence_frames", ws.transcript,
        ws.evidence, ws.lecture, ws.review, ws.images, ws.latex, ws.output,
        ws.reports, ws.logs, ws.stages,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    source_video_path = video_path
    if copy_source_video:
        target = ws.source / video_path.name
        if not target.exists() or target.stat().st_size != video_path.stat().st_size:
            shutil.copy2(video_path, target)
        source_video_path = target

    sha = _source_sha(video_path, ws.project_file if ws.project_file.exists() else None)
    stat = video_path.stat()
    created_at = datetime.now(timezone.utc).isoformat()
    if ws.project_file.exists():
        try:
            created_at = str(read_json(ws.project_file).get("created_at", created_at))
        except Exception:
            pass
    project_data = {
        "schema_version": "1.2",
        "project_name": root.name,
        "created_at": created_at,
        "source": {
            "original_path": str(video_path),
            "workspace_path": str(source_video_path),
            "sha256": sha,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        },
    }
    atomic_write_json(ws.project_file, project_data)
    return ws
