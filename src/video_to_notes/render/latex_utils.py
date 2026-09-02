from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..errors import StageError


_LATEX_ESCAPE_RE = re.compile(r'([#$%&_{}])')
_MATH_RE = re.compile(
    r'(\$\$.*?\$\$|\$.*?\$|\\\(.*?\\\)|\\\[.*?\\\])',
    flags=re.DOTALL,
)

# All source/config/template files remain UTF-8.  These replacements are only
# for mathematical/special Unicode characters in lecture content so that the
# generated .tex uses ordinary LaTeX commands instead of depending on glyph
# coverage in a particular font.
_UNICODE_MATH_COMMANDS: dict[str, str] = {
    # Geometry / relations
    "△": r"\triangle",
    "▲": r"\blacktriangle",
    "∠": r"\angle",
    "⊥": r"\perp",
    "∥": r"\parallel",
    "∦": r"\nparallel",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "≈": r"\approx",
    "≡": r"\equiv",
    "≅": r"\cong",
    "∼": r"\sim",
    "∽": r"\sim",
    "≌": r"\cong",
    "∝": r"\propto",
    "⊙": r"\odot",
    "⊕": r"\oplus",
    "⊖": r"\ominus",
    "⊗": r"\otimes",
    # Arithmetic / sets / calculus
    "±": r"\pm",
    "∓": r"\mp",
    "×": r"\times",
    "÷": r"\div",
    "·": r"\cdot",
    "∞": r"\infty",
    "∵": r"\because",
    "∴": r"\therefore",
    "∈": r"\in",
    "∉": r"\notin",
    "⊂": r"\subset",
    "⊆": r"\subseteq",
    "⊃": r"\supset",
    "⊇": r"\supseteq",
    "∪": r"\cup",
    "∩": r"\cap",
    "∅": r"\varnothing",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∂": r"\partial",
    "∇": r"\nabla",
    "ℓ": r"\ell",
    # Arrows / logic
    "→": r"\to",
    "←": r"\leftarrow",
    "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow",
    "⇐": r"\Leftarrow",
    "⇔": r"\Leftrightarrow",
    "¬": r"\neg",
    "∧": r"\land",
    "∨": r"\lor",
    # Greek (common in school mathematics)
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\varphi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
    # Superscript/subscript digits frequently emitted by OCR/LLMs
    "⁰": r"^{0}",
    "¹": r"^{1}",
    "²": r"^{2}",
    "³": r"^{3}",
    "⁴": r"^{4}",
    "⁵": r"^{5}",
    "⁶": r"^{6}",
    "⁷": r"^{7}",
    "⁸": r"^{8}",
    "⁹": r"^{9}",
    "₀": r"_{0}",
    "₁": r"_{1}",
    "₂": r"_{2}",
    "₃": r"_{3}",
    "₄": r"_{4}",
    "₅": r"_{5}",
    "₆": r"_{6}",
    "₇": r"_{7}",
    "₈": r"_{8}",
    "₉": r"_{9}",
    # Unicode punctuation variants that have direct TeX equivalents in math.
    "′": "'",
    "″": "''",
    # Unicode minus is semantically the ordinary mathematical minus.
    "−": "-",
}

# Characters that need context-sensitive LaTeX rather than a direct command.
_SPECIAL_MATH_CHARS = set(_UNICODE_MATH_COMMANDS) | {"°", "℃", "℉", "√", "½", "⅓", "⅔", "¼", "¾", "⅛", "⅜", "⅝", "⅞"}

_UNICODE_FRACTIONS = {
    "½": r"\frac{1}{2}",
    "⅓": r"\frac{1}{3}",
    "⅔": r"\frac{2}{3}",
    "¼": r"\frac{1}{4}",
    "¾": r"\frac{3}{4}",
    "⅛": r"\frac{1}{8}",
    "⅜": r"\frac{3}{8}",
    "⅝": r"\frac{5}{8}",
    "⅞": r"\frac{7}{8}",
}

_CIRCLED_NUMBERS = {
    chr(code): index
    for index, code in enumerate(range(0x2460, 0x2474), start=1)
}

# A compact ASCII-style math token.  If it contains at least one Unicode math
# symbol, the whole token is moved into explicit LaTeX math mode.  This turns
# e.g. △ABC, ∠A=30°, AB⊥CD, α+β=π into one clean math span.
_MATH_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_+\-*/=<>^().\[\]{}'′″°℃℉√½⅓⅔¼¾⅛⅜⅝⅞"
    + re.escape("".join(_UNICODE_MATH_COMMANDS.keys()))
    + r"]+"
)

# Full-width OCR variants that are safe to canonicalize before LaTeX output.
_ASCII_EQUIVALENTS = str.maketrans(
    {
        "＋": "+",
        "－": "-",
        "＝": "=",
        "＜": "<",
        "＞": ">",
        "／": "/",
        "＊": "*",
        "＃": "#",
        "％": "%",
        "＆": "&",
        "＿": "_",
        "　": " ",  # ideographic space
        "\u00a0": " ",  # non-breaking space
    }
)


def _normalize_math_content(text: str) -> str:
    """Convert Unicode math characters to LaTeX commands inside math mode."""
    text = text.translate(_ASCII_EQUIVALENTS)

    # √12 -> \sqrt{12}; √x -> \sqrt{x}.  A lone √ still becomes \sqrt{}.
    text = re.sub(
        r"√\s*([A-Za-z0-9]+)",
        lambda m: rf"\sqrt{{{m.group(1)}}}",
        text,
    )
    text = text.replace("√", r"\sqrt{}")

    # Degrees/temperature are expressed with TeX, not font glyphs.
    text = text.replace("℃", r"^{\circ}\mathrm{C}")
    text = text.replace("℉", r"^{\circ}\mathrm{F}")
    text = text.replace("°", r"^{\circ}")

    for char, latex in _UNICODE_FRACTIONS.items():
        text = text.replace(char, latex)

    # A TeX control word must be delimited before an immediately following
    # ASCII letter: ``\triangleABC`` would be parsed as one command, while
    # ``\triangle ABC`` is the intended ``\triangle`` followed by ``ABC``.
    pattern = re.compile("|".join(re.escape(c) for c in sorted(_UNICODE_MATH_COMMANDS, key=len, reverse=True)))

    def replace_command(match: re.Match[str]) -> str:
        latex = _UNICODE_MATH_COMMANDS[match.group(0)]
        next_char = text[match.end():match.end() + 1]
        if re.fullmatch(r"\\[A-Za-z]+", latex) and next_char and next_char.isascii() and next_char.isalpha():
            return latex + " "
        return latex

    text = pattern.sub(replace_command, text)
    return text


def _escape_plain_text_basic(text: str) -> str:
    text = text.replace("\\", "\uFFF0")
    text = _LATEX_ESCAPE_RE.sub(r"\\\1", text)
    text = text.replace("~", r"\textasciitilde{}")
    text = text.replace("^", r"\textasciicircum{}")
    text = text.replace("\uFFF0", r"\textbackslash{}")
    return text


def _escape_plain_text(text: str) -> str:
    """
    Escape prose while converting Unicode mathematical/special symbols into
    raw LaTeX fragments.  Chinese prose remains UTF-8; math symbols do not.
    """
    text = text.translate(_ASCII_EQUIVALENTS)
    raw_fragments: list[str] = []

    def stash(latex: str) -> str:
        index = len(raw_fragments)
        raw_fragments.append(latex)
        return f"\uE000{index}\uE001"

    # Convert compact mathematical expressions as a whole so that we can use
    # explicit LaTeX math mode instead of an implicit wrapper.
    def replace_math_token(match: re.Match[str]) -> str:
        token = match.group(0)
        if not any(char in _SPECIAL_MATH_CHARS for char in token):
            return token
        return stash(r"\(" + _normalize_math_content(token) + r"\)")

    text = _MATH_TOKEN_RE.sub(replace_math_token, text)

    # Circled numbers are text markers, not mathematics.  Emit LaTeX instead
    # of relying on Unicode glyph U+2460..U+2473.
    for char, number in _CIRCLED_NUMBERS.items():
        if char in text:
            text = text.replace(char, stash(rf"\textcircled{{{number}}}"))

    # If a known Unicode math symbol was separated by whitespace/punctuation
    # and therefore not part of a compact token, still render it explicitly in
    # math mode rather than leaving a raw Unicode glyph in the .tex file.
    for char in sorted(_SPECIAL_MATH_CHARS, key=len, reverse=True):
        if char in text:
            text = text.replace(char, stash(r"\(" + _normalize_math_content(char) + r"\)"))

    # Common typographic symbols that do not need Unicode in generated TeX.
    text = text.replace("…", stash(r"\ldots{}"))
    text = text.replace("—", "---")
    text = text.replace("–", "--")

    escaped = _escape_plain_text_basic(text)
    for index, latex in enumerate(raw_fragments):
        escaped = escaped.replace(f"\uE000{index}\uE001", latex)
    return escaped


def _normalize_existing_math_span(part: str) -> str:
    if part.startswith("$$") and part.endswith("$$"):
        return "$$" + _normalize_math_content(part[2:-2]) + "$$"
    if part.startswith("$") and part.endswith("$"):
        return "$" + _normalize_math_content(part[1:-1]) + "$"
    if part.startswith(r"\(") and part.endswith(r"\)"):
        return r"\(" + _normalize_math_content(part[2:-2]) + r"\)"
    if part.startswith(r"\[") and part.endswith(r"\]"):
        return r"\[" + _normalize_math_content(part[2:-2]) + r"\]"
    return part


def tex_escape(value: Any) -> str:
    """
    Escape ordinary UTF-8 prose for LaTeX while preserving explicit math spans.

    Chinese text remains UTF-8.  Unicode mathematical/special symbols are
    normalized to ordinary LaTeX commands in explicit math mode, so generated
    TeX does not depend on fonts containing symbols such as △, ∠, ⊥ or °.
    """
    if value is None:
        return ""

    text = str(value)
    parts = _MATH_RE.split(text)
    out: list[str] = []

    for part in parts:
        if not part:
            continue
        if _MATH_RE.fullmatch(part):
            out.append(_normalize_existing_math_span(part))
        else:
            out.append(_escape_plain_text(part))

    return "".join(out)


def find_raw_unicode_math_symbols(text: str) -> list[tuple[str, str]]:
    """Return remaining Unicode math/symbol code points after normalization."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for char in text:
        if ord(char) < 128 or char in seen:
            continue
        category = unicodedata.category(char)
        # Sm is mathematical symbol; No covers superscripts/circled numbers.
        # So is broad, therefore only flag known math-like geometric/symbolic
        # ranges that commonly leak from OCR/LLM output.
        is_math_like_so = (
            category == "So"
            and (
                0x2100 <= ord(char) <= 0x2BFF
                or 0x2460 <= ord(char) <= 0x24FF
            )
        )
        if category in {"Sm", "No"} or is_math_like_so:
            seen.add(char)
            found.append((char, f"U+{ord(char):04X}"))
    return found


def build_environment(template_path: Path) -> Environment:
    if not template_path.exists():
        raise StageError(f"LaTeX 模板不存在: {template_path}")

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tex"] = tex_escape
    return env
