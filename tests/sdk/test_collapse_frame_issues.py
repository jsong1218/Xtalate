"""``collapse_frame_issues`` — per-frame issue aggregation (Part 3 §5; the v0.7 review, F9).

A parser that walks a trajectory emits one :class:`ParseIssue` *per frame* for a per-frame
condition (an unmapped calculator result carried verbatim, a non-modelled constraint). A
thousand-frame file then floods every surface — the CLI's ``inspect`` lines, the Conversion
Report's ``warnings``, the Web UI — with a thousand identical sentences that differ only in
``location``. This helper collapses a run of issues that are identical **except** for a
``frame N`` location into a single issue whose message names the frame range, so the loss is
reported once and in full (**P1**) rather than a thousand times.
"""

from __future__ import annotations

from xtalate.sdk import ParseIssue, collapse_frame_issues


def _issue(code: str, message: str, frame: int | None, severity: str = "warning") -> ParseIssue:
    loc = None if frame is None else f"frame {frame}"
    return ParseIssue(severity=severity, code=code, message=message, location=loc)  # type: ignore[arg-type]


def test_empty_is_empty() -> None:
    assert collapse_frame_issues([]) == []


def test_single_frame_issue_is_unchanged() -> None:
    # One frame carried it: nothing to collapse, so the message and location are left exactly as
    # the parser wrote them — no spurious "(frames …)" suffix for a genuine single-frame finding.
    issues = [_issue("C", "carried verbatim", 7)]
    out = collapse_frame_issues(issues)
    assert len(out) == 1
    assert out[0].message == "carried verbatim"
    assert out[0].location == "frame 7"


def test_contiguous_run_collapses_to_one_with_range() -> None:
    issues = [_issue("C", "carried verbatim", i) for i in range(1000)]
    out = collapse_frame_issues(issues)
    assert len(out) == 1
    assert out[0].message == "carried verbatim (frames 0-999)"
    # The per-frame location no longer applies once aggregated; the range lives in the message so
    # every renderer shows it, including the location-less ReportWarning the conversion report uses.
    assert out[0].location is None
    assert out[0].code == "C"
    assert out[0].severity == "warning"


def test_non_contiguous_frames_are_compressed_into_parts() -> None:
    frames = [0, 1, 2, 4, 7, 8]
    issues = [_issue("C", "m", i) for i in frames]
    out = collapse_frame_issues(issues)
    assert len(out) == 1
    assert out[0].message == "m (frames 0-2, 4, 7-8)"


def test_distinct_messages_do_not_collapse() -> None:
    # Two unmapped keys carried on the same frames are two different findings — keep them apart.
    issues = [
        _issue("C", "carried 'free_energy'", 0),
        _issue("C", "carried 'dipole'", 0),
        _issue("C", "carried 'free_energy'", 1),
        _issue("C", "carried 'dipole'", 1),
    ]
    out = collapse_frame_issues(issues)
    assert [i.message for i in out] == [
        "carried 'free_energy' (frames 0-1)",
        "carried 'dipole' (frames 0-1)",
    ]


def test_severity_and_code_separate_groups() -> None:
    issues = [
        _issue("A", "m", 0),
        _issue("B", "m", 0),
        _issue("A", "m", 1, severity="error"),
        _issue("A", "m", 1),
    ]
    out = collapse_frame_issues(issues)
    # (A/warning), (B/warning), (A/error) are three groups; the two (A/warning) frames collapse.
    assert len(out) == 3
    a_warn = next(i for i in out if i.code == "A" and i.severity == "warning")
    assert a_warn.message == "m (frames 0-1)"


def test_non_frame_locations_pass_through_untouched() -> None:
    # A "line 5" or block location is not a per-frame condition — never collapse those, even when
    # the message repeats: they may be genuinely distinct findings at different offsets.
    issues = [
        ParseIssue(severity="warning", code="L", message="m", location="line 5"),
        ParseIssue(severity="warning", code="L", message="m", location="line 9"),
    ]
    assert collapse_frame_issues(issues) == issues


def test_order_is_preserved_at_first_occurrence() -> None:
    issues = [
        _issue("C", "carried", 0),
        ParseIssue(severity="warning", code="OTHER", message="one-off", location="line 1"),
        _issue("C", "carried", 1),
    ]
    out = collapse_frame_issues(issues)
    # The collapsed group takes the position of its first member; the interleaved one-off stays put.
    assert [i.code for i in out] == ["C", "OTHER"]
    assert out[0].message == "carried (frames 0-1)"
