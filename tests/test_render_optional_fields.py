from pathlib import Path

from video_to_notes.config import resolve_resource_path

from video_to_notes.render.context import build_render_context
from video_to_notes.render.latex_utils import build_environment


def test_template_allows_sparse_optional_metadata():
    template_path = resolve_resource_path("package:lecture.tex.j2", default_name="lecture.tex.j2")

    lecture = {
        "schema_version": "1.0",
        "stage": "review_draft",
        "metadata": {"title": "倍长中线2"},
        "overview": {},
        "sections": [
            {
                "id": "sec_01",
                "title": "倍长中线",
                "blocks": [
                    {
                        "id": "blk_001",
                        "type": "knowledge",
                        "content": "构造倍长中线。",
                    }
                ],
            }
        ],
        "problems": [
            {
                "id": "P01",
                "section_id": "sec_01",
                "statement": {"content": "证明结论。"},
                "teacher_solution": None,
                "teacher_answer": None,
            }
        ],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }

    env = build_environment(template_path)
    template = env.get_template(template_path.name)
    rendered = template.render(**build_render_context(lecture))

    assert "倍长中线2" in rendered
    assert "构造倍长中线" in rendered
    assert "视频来源" not in rendered
    assert "视频时长" not in rendered
