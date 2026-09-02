from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..errors import StageError


def prepare_publication_images(
    lecture: dict[str, Any],
    *,
    workspace_root: Path,
    latex_dir: Path,
    fail_on_missing: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    image_dir = latex_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    copied: list[dict[str, Any]] = []
    missing: list[str] = []

    for index, figure in enumerate(lecture.get("figures", []), start=1):
        source = (
            figure.get("publication_path")
            or figure.get("evidence_path")
            or figure.get("path")
        )

        if not source:
            missing.append(str(figure.get("id", f"figure_{index}")))
            continue

        src = Path(str(source))
        if not src.is_absolute():
            src = workspace_root / src

        if not src.exists():
            missing.append(str(src))
            continue

        ext = src.suffix.lower() or ".jpg"
        name = figure.get("publication_name")
        if not name:
            name = f"fig_{index:03d}{ext}"

        dst = image_dir / str(name)
        shutil.copy2(src, dst)

        figure["publication_name"] = dst.name
        copied.append({
            "figure_id": figure.get("id"),
            "source": str(src),
            "destination": str(dst),
        })

    if missing and fail_on_missing:
        raise StageError(
            "存在缺失图片: " + "; ".join(missing)
        )

    return copied, missing
