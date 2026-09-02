from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..errors import StageError


def resolve_latex_engine(engine: str) -> Path:
    configured = Path(engine)
    if configured.exists():
        return configured

    found = shutil.which(engine)
    if found:
        return Path(found)

    raise StageError(
        f"找不到 LaTeX 引擎 {engine!r}。请安装 TeX Live/MiKTeX "
        "并确保 xelatex 位于 PATH，或在 config/default.yaml 中指定路径。"
    )


def inspect_latex_log(log_text: str) -> dict[str, int]:
    return {
        "latex_errors": len(re.findall(r"^!", log_text, flags=re.MULTILINE)),
        "undefined_control_sequence": len(
            re.findall(r"Undefined control sequence", log_text)
        ),
        "missing_characters": len(
            re.findall(r"Missing character:", log_text)
        ),
        "overfull_hbox": len(
            re.findall(r"Overfull \\hbox", log_text)
        ),
    }


def compile_xelatex(
    *,
    engine: Path,
    tex_path: Path,
    runs: int,
    timeout_seconds: int,
    interaction: str,
    halt_on_error: bool,
) -> dict[str, Any]:
    latex_dir = tex_path.parent
    command = [
        str(engine),
        f"-interaction={interaction}",
        "-file-line-error",
    ]
    if halt_on_error:
        command.append("-halt-on-error")
    command.append(tex_path.name)

    run_results = []

    for index in range(max(1, int(runs))):
        try:
            proc = subprocess.run(
                command,
                cwd=latex_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
            )
        except subprocess.TimeoutExpired as exc:
            raise StageError(
                f"XeLaTeX 第 {index + 1} 次编译超时。"
            ) from exc

        run_results.append({
            "run": index + 1,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        })

        if proc.returncode != 0:
            raise StageError(
                f"XeLaTeX 第 {index + 1} 次编译失败，exit={proc.returncode}。"
            )

    pdf_path = tex_path.with_suffix(".pdf")
    log_path = tex_path.with_suffix(".log")

    if not pdf_path.exists():
        raise StageError("XeLaTeX 返回成功，但没有生成 PDF。")

    log_text = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else ""
    )

    return {
        "runs": run_results,
        "pdf_path": pdf_path,
        "log_path": log_path,
        "log_metrics": inspect_latex_log(log_text),
    }
