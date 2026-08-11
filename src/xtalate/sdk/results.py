"""Parse results and the error contract (MASTER_SPEC Part 3 §5).

Every parser shares one result/error shape so the Discovery Engine, Conversion Engine, and
API handle malformed files uniformly. The load-bearing rule (§5 rule 1): **warnings
accompany success; errors preclude it.** There is no "best-effort object plus errors"
middle state — a half-parsed structure presented as data is silent loss (P1).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xtalate.schema import CanonicalObject


class ParseIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["warning", "error"]
    code: str  # Stable machine code, e.g. "XYZ_INCONSISTENT_ATOM_COUNT".
    message: str  # Human-readable, specific: what, where, why it matters.
    location: str | None = None  # e.g. "line 4192", "frame 17", "data block 2".
    # Machine-consumable hint the Recovery Engine can act on, e.g. "supply_species".
    recovery_hint: str | None = None


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical: CanonicalObject  # Present iff parse succeeded (possibly with warnings).
    issues: list[ParseIssue] = Field(default_factory=list)  # Warnings; empty for a clean parse.


class ParseError(Exception):
    """Raised when no valid CanonicalObject can be produced (§5). Carries ``issues`` with
    at least one error-severity entry."""

    def __init__(self, issues: list[ParseIssue], message: str | None = None) -> None:
        errors = [i for i in issues if i.severity == "error"]
        if not errors:
            raise ValueError("ParseError requires at least one error-severity ParseIssue")
        self.issues = issues
        super().__init__(message or errors[0].message)


class FrameLimitExceeded(Exception):
    """A trajectory's frame count exceeded the caller's ``max_frames`` cap during the read.

    Carries the count-so-far and the cap. Raised **mid-stream** — by the frame-reading seam while
    frames are still being read, before the remaining frames are materialized (M39-S3, the M37
    finding-F1 / D128 contract-honesty fix) — so a stated cap is a real gate on worker memory, not
    an after-the-fact observation. Distinct from :class:`ParseError`: the file itself is fine; the
    *size of the trajectory* is the refusal. The HTTP service translates it to ``422
    FRAME_LIMIT_EXCEEDED`` on the failed job (the ``backend/error_codes.py`` authority); the CLI
    and library callers pass no ``max_frames`` and are unaffected (default ``None``)."""

    def __init__(self, frame_count: int, max_frames: int) -> None:
        self.frame_count = frame_count
        self.max_frames = max_frames
        super().__init__(
            f"trajectory exceeds the max_frames limit: {frame_count} frames read, "
            f"limit {max_frames}"
        )


# --- Per-frame issue aggregation (Part 3 §5; the v0.7 review, F9) --------------------------------

_FRAME_LOCATION = re.compile(r"^frame (\d+)$")


def _compress_frames(frames: list[int]) -> str:
    """Sorted unique frame indices → a compact range phrase, e.g. ``[0,1,2,4,7,8]`` → ``"frames
    0-2, 4, 7-8"``. Indices are 0-based, matching the ``frame N`` locations parsers emit and the
    0-based frame convention used everywhere else (Part 2 §3.11)."""
    xs = sorted(set(frames))
    parts: list[str] = []
    start = prev = xs[0]
    for x in xs[1:]:
        if x == prev + 1:
            prev = x
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = x
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return "frames " + ", ".join(parts)


def collapse_frame_issues(issues: list[ParseIssue]) -> list[ParseIssue]:
    """Collapse runs of issues identical except for a ``frame N`` location into one per group.

    A per-frame condition — a carried-verbatim calculator result, a non-modelled constraint —
    makes a parser append one otherwise-identical :class:`ParseIssue` for every frame it appears
    in. On a long trajectory that is thousands of duplicate lines in the Discovery Report, the
    Conversion Report's ``warnings``, and the Web UI. This aggregates them: issues sharing
    ``(severity, code, message, recovery_hint)`` **and** all carrying a ``frame N`` location are
    reduced to a single issue whose message gains a ``(frames 0-999)`` suffix naming exactly which
    frames it covers — the loss reported once and in full (**P1**), never a thousand times.

    The frame range is folded into the *message* (not just the location) because the location-less
    ``ReportWarning`` the conversion report carries would otherwise drop it, and because the CLI
    renders messages, not locations — so this one place makes every surface show the range without
    a per-renderer change. Group order follows first occurrence; a genuine single-frame finding, a
    non-``frame`` location (``line 5``, a data block), and a distinct message are left untouched.
    """
    frames_by_key: dict[tuple[str, str, str, str | None], list[int]] = {}
    first_issue: dict[tuple[str, str, str, str | None], ParseIssue] = {}
    # Non-frame issues are emitted inline; a placeholder marks where a collapsed group belongs so
    # the output preserves the input order at each group's first occurrence.
    slots: list[ParseIssue | tuple[str, str, str, str | None]] = []
    for issue in issues:
        match = _FRAME_LOCATION.match(issue.location or "")
        if match is None:
            slots.append(issue)
            continue
        key = (issue.severity, issue.code, issue.message, issue.recovery_hint)
        if key not in frames_by_key:
            frames_by_key[key] = []
            first_issue[key] = issue
            slots.append(key)
        frames_by_key[key].append(int(match.group(1)))

    result: list[ParseIssue] = []
    for slot in slots:
        if isinstance(slot, ParseIssue):
            result.append(slot)
            continue
        frames = frames_by_key[slot]
        base = first_issue[slot]
        if len(frames) == 1:
            result.append(base)  # a real single-frame finding — leave it verbatim.
        else:
            span = _compress_frames(frames)
            result.append(
                base.model_copy(update={"message": f"{base.message} ({span})", "location": None})
            )
    return result
