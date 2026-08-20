from __future__ import annotations

import re
from dataclasses import dataclass

_SEMVER_RE = re.compile(
    r"^v(0|[1-9]\d*)"
    r"(?:\.(0|[1-9]\d*))?"
    r"(?:\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r")?$"
)


@dataclass(frozen=True, slots=True)
class _Semver:
    major: str
    minor: str
    patch: str
    prerelease: tuple[str, ...]


def compare_semver(left: str, right: str) -> int | None:
    parsed_left = _parse_semver(left)
    parsed_right = _parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return None

    for left_value, right_value in (
        (parsed_left.major, parsed_right.major),
        (parsed_left.minor, parsed_right.minor),
        (parsed_left.patch, parsed_right.patch),
    ):
        comparison = _compare_integer_strings(left_value, right_value)
        if comparison != 0:
            return comparison
    return _compare_prerelease(parsed_left.prerelease, parsed_right.prerelease)


def _parse_semver(value: str) -> _Semver | None:
    trimmed = value.strip()
    normalized = trimmed if trimmed.startswith("v") else f"v{trimmed}"
    match = _SEMVER_RE.fullmatch(normalized)
    if match is None:
        return None
    prerelease = tuple((match.group(4) or "").split(".")) if match.group(4) else ()
    if any(identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0") for identifier in prerelease):
        return None
    return _Semver(
        major=match.group(1),
        minor=match.group(2) or "0",
        patch=match.group(3) or "0",
        prerelease=prerelease,
    )


def _compare_integer_strings(left: str, right: str) -> int:
    if left == right:
        return 0
    if len(left) != len(right):
        return -1 if len(left) < len(right) else 1
    return -1 if left < right else 1


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1
    for left_identifier, right_identifier in zip(left, right, strict=False):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        if left_numeric:
            return _compare_integer_strings(left_identifier, right_identifier)
        return -1 if left_identifier < right_identifier else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1
