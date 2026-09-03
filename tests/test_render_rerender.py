import json
import logging
from pathlib import Path

from video_to_notes.render.stage import run_render_stage
from video_to_notes.stages import StageContext


def test_render_accepts_audited_and_clears_stale_audit(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / "lecture").mkdir(parents=True)
    (ws / "reports").mkdir(parents=True)
    lecture = {
        "stage": "audited",
        "audit": {"verdict": "PASS_WITH_NOTES", "report_json": "old.json"},
        "metadata": {"title": "测试"},
        "overview": {}, "sections": [], "problems": [], "supplements": [],
        "figures": [], "summary": [], "review": {"issues": []},
    }
    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(lecture, ensure_ascii=False), encoding="utf-8"
    )

    def fake_compile_xelatex(**kwargs):
        tex_path = Path(kwargs["tex_path"])
        pdf_path = tex_path.with_suffix(".pdf")
        log_path = tex_path.with_suffix(".log")
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        log_path.write_text("", encoding="utf-8")
        return {
            "pdf_path": pdf_path,
            "log_path": log_path,
            "log_metrics": {
                "latex_errors": 0,
                "missing_characters": 0,
                "overfull_hbox": 0,
            },
        }

    monkeypatch.setattr("video_to_notes.render.stage.compile_xelatex", fake_compile_xelatex)
    config = {
        "project": {"project_root": str(tmp_path)},
        "reconstruction": {},
        "render": {
            "template": "package:lecture.tex.j2",
            "engine": "xelatex",
            "runs": 1,
            "timeout_seconds": 30,
            "interaction": "nonstopmode",
            "halt_on_error": True,
            "fail_on_missing_image": True,
            "fail_on_missing_character": True,
        },
    }
    run_render_stage(StageContext(
        stage="render", workspace_root=ws, config=config, logger=logging.getLogger("test")
    ))
    rendered = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    assert rendered["stage"] == "rendered"
    assert "audit" not in rendered
    assert (ws / "output" / "lecture.pdf").exists()
