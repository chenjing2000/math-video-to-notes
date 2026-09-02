from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ..config import resolve_resource_path
from ..errors import StageError
from ..stages import StageContext
from ..util import atomic_write_json, read_json
from ..reconstruction.figures import bind_problem_figures
from .compiler import compile_xelatex, resolve_latex_engine
from .context import build_render_context
from .images import prepare_publication_images
from .latex_utils import build_environment, find_raw_unicode_math_symbols


def _resolve_project_root(ctx: StageContext) -> Path:
    configured = ctx.config.get("project", {}).get("project_root")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    return Path.cwd().resolve()


def run_render_stage(ctx: StageContext) -> None:
    logger: logging.Logger = ctx.logger
    cfg = ctx.config["render"]
    project_root = _resolve_project_root(ctx)

    lecture_path = ctx.workspace_root / "lecture" / "lecture.json"
    if not lecture_path.exists():
        raise StageError(
            f"缺少 lecture.json: {lecture_path}"
        )

    lecture = read_json(lecture_path)
    if not isinstance(lecture, dict):
        raise StageError("lecture.json 根节点必须为 object。")

    if str(lecture.get("stage", "")) not in {
        "review_draft",
        "rendered",
    }:
        raise StageError(
            "render stage 只接受 review_draft/rendered。"
        )

    template_path = resolve_resource_path(cfg.get("template", "package:lecture.tex.j2"), default_name="lecture.tex.j2")

    # Sprint 10 fallback: bind figures deterministically at render time too.
    # This lets an existing reconstruction/completion/review workspace gain figures
    # without rerunning the expensive visual/transcription stages.
    timeline_path = ctx.workspace_root / "evidence" / "timeline.json"
    figure_binding_report = {"figures_bound": 0, "problems_bound": [], "problems_inferred": [], "problems_unresolved": []}
    if timeline_path.exists():
        timeline_data = read_json(timeline_path)
        timeline = timeline_data.get("timeline", []) if isinstance(timeline_data, dict) else []
        if isinstance(timeline, list):
            figure_binding_report = bind_problem_figures(
                lecture,
                timeline,
                workspace_root=ctx.workspace_root,
                infer_from_statement=bool(ctx.config.get("reconstruction", {}).get("infer_problem_figures", True)),
                max_figures_per_problem=int(ctx.config.get("reconstruction", {}).get("max_figures_per_problem", 2)),
            )
            atomic_write_json(lecture_path, lecture)

    latex_dir = ctx.workspace_root / "latex"
    output_dir = ctx.workspace_root / "output"
    latex_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied_images, missing_images = prepare_publication_images(
        lecture,
        workspace_root=ctx.workspace_root,
        latex_dir=latex_dir,
        fail_on_missing=bool(cfg.get("fail_on_missing_image", True)),
    )

    context = build_render_context(lecture)
    env = build_environment(template_path)
    template = env.get_template(template_path.name)

    tex_text = template.render(**context)

    # Generated TeX may contain UTF-8 Chinese prose, but mathematical/special
    # Unicode symbols must already have been normalized to LaTeX commands.
    remaining_symbols = find_raw_unicode_math_symbols(tex_text)
    if remaining_symbols:
        details = ", ".join(f"{char} ({code})" for char, code in remaining_symbols)
        raise StageError(
            "生成的 LaTeX 仍含未规范化的 Unicode 数学/特殊符号: " + details
        )

    tex_path = latex_dir / "lecture.tex"
    tex_path.write_text(tex_text, encoding="utf-8")

    engine = resolve_latex_engine(str(cfg.get("engine", "xelatex")))
    logger.info("[render] engine=%s", engine)
    logger.info("[render] template=%s", template_path)

    compile_result = compile_xelatex(
        engine=engine,
        tex_path=tex_path,
        runs=int(cfg.get("runs", 2)),
        timeout_seconds=int(cfg.get("timeout_seconds", 180)),
        interaction=str(cfg.get("interaction", "nonstopmode")),
        halt_on_error=bool(cfg.get("halt_on_error", True)),
    )

    metrics = compile_result["log_metrics"]

    if (
        bool(cfg.get("fail_on_missing_character", True))
        and metrics["missing_characters"] > 0
    ):
        raise StageError(
            f"LaTeX 日志发现 Missing character: {metrics['missing_characters']}"
        )

    if metrics["latex_errors"] > 0:
        raise StageError(
            f"LaTeX 日志发现错误: {metrics['latex_errors']}"
        )

    final_pdf = output_dir / "lecture.pdf"
    shutil.copy2(compile_result["pdf_path"], final_pdf)

    lecture["stage"] = "rendered"
    atomic_write_json(lecture_path, lecture)

    report = {
        "schema_version": "1.0",
        "stage": "render",
        "template": str(template_path),
        "engine": str(engine),
        "runs": int(cfg.get("runs", 2)),
        "images_copied": len(copied_images),
        "figure_binding": figure_binding_report,
        "missing_images": missing_images,
        "latex_metrics": metrics,
        "quality": {
            "complete": metrics.get("latex_errors", 0) == 0
            and metrics.get("missing_characters", 0) == 0
            and not missing_images
            and not figure_binding_report.get("problems_unresolved", []),
            "unresolved_figures": figure_binding_report.get("problems_unresolved", []),
        },
        "outputs": {
            "tex": str(tex_path),
            "pdf": str(final_pdf),
            "log": str(compile_result["log_path"]),
        },
    }
    atomic_write_json(
        ctx.workspace_root / "reports" / "render_report.json",
        report,
    )

    logger.info(
        "[render] pdf=%s errors=%d missing_chars=%d overfull=%d",
        final_pdf,
        metrics["latex_errors"],
        metrics["missing_characters"],
        metrics["overfull_hbox"],
    )
