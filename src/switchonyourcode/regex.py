from __future__ import annotations

import re

from .errors import EvaluationFailure

_UNSUPPORTED_RE2_PATTERNS = (
    re.compile(r"\\[1-9]"),
    re.compile(r"\\k<"),
    re.compile(r"\(\?P="),
    re.compile(r"\(\?="),
    re.compile(r"\(\?!"),
    re.compile(r"\(\?<="),
    re.compile(r"\(\?<!"),
    re.compile(r"\(\?>"),
    re.compile(r"\(\?\("),
)


def compile_re2(pattern: str) -> re.Pattern[str]:
    for unsupported in _UNSUPPORTED_RE2_PATTERNS:
        if unsupported.search(pattern):
            raise EvaluationFailure("PARSE_ERROR", "regular expression uses syntax unsupported by RE2")
    translated = pattern.replace(r"\z", r"\Z")
    try:
        return re.compile(translated)
    except re.error as exc:
        raise EvaluationFailure("PARSE_ERROR", str(exc)) from exc
