from video_to_notes.completion.assessment import (
    infer_requires_solution,
    infer_solution_completeness,
)


def test_infers_incomplete_teacher_proof_from_text_marker():
    problem = {
        "id": "P03",
        "statement": {"content": "求证：CD=2CE。"},
        "teacher_solution": {
            "content": "延长 CE 至 P，使 EP=CE；分块证据未完整呈现后续证明。",
            "status": "confirmed",
        },
        "teacher_answer": {"content": "CD=2CE"},
    }
    assert infer_requires_solution(problem) is True
    assert infer_solution_completeness(problem) == "incomplete"
