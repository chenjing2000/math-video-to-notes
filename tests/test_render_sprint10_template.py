from video_to_notes.config import resolve_resource_path
from video_to_notes.render.context import build_render_context
from video_to_notes.render.latex_utils import build_environment


def test_template_uses_single_publication_solution_and_unresolved_note_once():
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
            "publication_solution": {"content": "Sol 最终解法。", "review_status": "revised"},
            "teacher_answer": {"content": "$CD=2CE$"},
            "publication_answer": {"content": "$CD=2CE$", "review_status": "verified"},
            "math_review_unresolved": True,
        }],
        "figures": [{
            "id": "fig_P03_01", "problem_id": "P03", "publication_name": "fig_001.jpg",
            "caption": "题目图", "width": "0.78",
        }],
        "supplements": [{
            "id": "sup_001", "target_id": "P03", "type": "derived_solution",
            "content": "这里给出原始补充证明。",
        }],
        "summary": [],
        "review": {"issues": [{"target_id": "P03", "message": "不应进入 PDF"}]},
    }
    context = build_render_context(lecture)
    env = build_environment(template_path)
    tex = env.get_template(template_path.name).render(**context)
    assert "fig\\_001.jpg" in tex
    assert "Sol 最终解法" in tex
    assert "老师只完成构造" not in tex
    assert "这里给出原始补充证明" not in tex
    assert tex.count("本题 GPT sol 未处理完成") == 1
    assert "不应进入 PDF" not in tex
    assert "【审校提示】" not in tex
