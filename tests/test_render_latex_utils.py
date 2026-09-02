from video_to_notes.render.compiler import inspect_latex_log
from video_to_notes.render.latex_utils import (
    find_raw_unicode_math_symbols,
    tex_escape,
)


def test_tex_escape():
    assert tex_escape("A&B") == r"A\&B"
    assert tex_escape("50%") == r"50\%"
    assert tex_escape(r"$\alpha + x$") == r"$\alpha + x$"
    assert tex_escape(r"50% 且 $a_b=c$") == r"50\% 且 $a_b=c$"


def test_unicode_math_is_normalized_to_explicit_latex_math():
    assert tex_escape("△ABC") == r"\(\triangle ABC\)"
    assert tex_escape("在△ABC中") == r"在\(\triangle ABC\)中"
    assert tex_escape("∠A=30°") == r"\(\angle A=30^{\circ}\)"
    assert tex_escape("AB⊥CD") == r"\(AB\perp CD\)"
    assert tex_escape("a≤b") == r"\(a\le b\)"
    assert tex_escape("α+β=π") == r"\(\alpha+\beta=\pi\)"
    assert tex_escape("√12") == r"\(\sqrt{12}\)"


def test_unicode_math_inside_existing_math_span_is_not_nested():
    assert tex_escape("$△ABC$") == r"$\triangle ABC$"
    assert tex_escape(r"\(∠A=30°\)") == r"\(\angle A=30^{\circ}\)"


def test_textual_unicode_markers_use_latex_not_font_mapping():
    assert tex_escape("① 方法") == r"\textcircled{1} 方法"
    assert tex_escape("第一步…第二步") == r"第一步\ldots{}第二步"
    assert tex_escape("A—B") == "A---B"


def test_no_raw_unicode_math_symbols_remain_after_normalization():
    rendered = tex_escape("在△ABC中，∠A=30°，AB⊥CD，且α+β≤π。①")
    assert find_raw_unicode_math_symbols(rendered) == []
    for char in "△∠°⊥αβ≤π①":
        assert char not in rendered


def test_inspect_latex_log():
    log = """
! LaTeX Error: Something bad.
Undefined control sequence.
Missing character: There is no ①
Overfull \\hbox (2.0pt too wide)
"""
    metrics = inspect_latex_log(log)
    assert metrics["latex_errors"] == 1
    assert metrics["undefined_control_sequence"] == 1
    assert metrics["missing_characters"] == 1
    assert metrics["overfull_hbox"] == 1
