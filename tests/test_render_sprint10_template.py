from pathlib import Path

from video_to_notes.config import resolve_resource_path

from video_to_notes.render.context import build_render_context
from video_to_notes.render.latex_utils import build_environment


def test_template_renders_unassigned_figure_and_derived_solution():
    template_path = resolve_resource_path("package:lecture.tex.j2", default_name="lecture.tex.j2")
    lecture = {
        "metadata": {"title": "测试"},
        "overview": {},
        "sections": [],
        "problems": [{
            "id": "P03",
            "title": "例题 3",
            "statement": {"content": "求证 $CD=2CE$"},
            "teacher_solution": {"content": "老师只完成构造。"},
            "teacher_answer": {"content": "$CD=2CE$"},
        }],
        "figures": [{
            "id": "fig_P03_01",
            "problem_id": "P03",
            "publication_name": "fig_001.jpg",
            "caption": "题目图",
            "width": "0.78",
        }],
        "supplements": [{
            "id": "sup_001",
            "target_id": "P03",
            "type": "derived_solution",
            "content": "这里给出完整补充证明。",
        }],
        "summary": [],
        "review": {"issues": []},
    }
    context = build_render_context(lecture)
    env = build_environment(template_path)
    tex = env.get_template(template_path.name).render(**context)
    assert "fig\\_001.jpg" in tex
    assert "\\begin{derivedsolution}" in tex
    assert "【讲义补充推导】" in tex
