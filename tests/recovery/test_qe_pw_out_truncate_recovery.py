"""``truncate_at_last_valid_frame`` recovery on the `qe_pw_out` reader (v1.4 M52-S3; D197).

The `qe_pw_out` counterpart of OUTCAR's torn-tail recovery (M43-S3/D166) and XDATCAR's (M13):
a run killed while writing ionic step *k* leaves steps 0..k-1 as perfectly good science behind
a corrupt tail. Keeping that prefix is the **user's** explicit choice, never the parser's —
without a preset the corrupt file is refused; with one, the kept steps and the dropped tail are
both recorded (P1, P4). No new recovery machinery: the shared ``truncate_corrupt_tail``
scenario (Revision 1.15) is reused verbatim — `qe_pw_out` wires into it by raising the hinted
``QEOUT_TRUNCATED`` error and implementing ``parse_recover``, exactly as outcar/xdatcar do.

The torn fixtures are real slices of the run's own committed rendering (``render_pw_out`` — the
byte-for-byte `relax` golden): a process kill is a file that simply *stops*, so each torn shape
is the full text cut mid-write, never a hand-authored fragment.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.parsers._qe_run import render_pw_out
from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, main
from xtalate.conversion.parse_recovery import ParseRecovery, parse_with_recovery
from xtalate.parsers.qe_pw_out import make_qe_pw_out_parser
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

_REGISTRY = default_registry()
_TRUNCATE: dict[str, dict[str, object]] = {"truncate_corrupt_tail": {"choice": "truncate"}}

#: The full three-step relax run (byte-for-byte the committed `relax` golden).
_FULL = render_pw_out("7x")
_STEP3 = _FULL.index("iteration #  3")
#: Steps 1–2 complete (everything through the end of step 2's positions card).
_GOOD = _FULL[:_STEP3]

#: Step 3's force block stopped after its first row (the file ends mid-table).
TORN_MID_FORCES = _FULL[: _FULL.index("     atom 2 type 2   force =", _STEP3)]
#: Step 3's positions card stopped after its first row (the file ends mid-table).
TORN_MID_POSITIONS = _FULL[: _FULL.index("     H   3.270000000", _STEP3)]
#: The very first step's force block is torn: there is no valid prefix to keep.
FIRST_STEP_TORN = _FULL[: _FULL.index("     atom 2 type 2   force =")]

#: Two good steps, then a step whose force block carries a 4th row — a structural
#: inconsistency, not a torn tail, so `truncate` must not quietly turn it into a plausible
#: 2-frame trajectory.
_EXTRA_ROW = "     atom 4 type 2   force =     -0.00600000   +0.00800000   -0.00200000\n"
INCONSISTENT = _GOOD + _FULL[_STEP3:].replace(
    "     atom 3 type 2   force =     -0.00400000   +0.00700000   -0.00100000\n",
    "     atom 3 type 2   force =     -0.00400000   +0.00700000   -0.00100000\n" + _EXTRA_ROW,
)


def _recover(data: str, choices: dict[str, dict[str, object]] | None = None) -> ParseRecovery:
    return parse_with_recovery(
        _REGISTRY, data.encode(), filename="pw.out", recovery_choices=choices or _TRUNCATE
    )


@pytest.mark.parametrize(
    ("name", "data"),
    [("torn_mid_forces", TORN_MID_FORCES), ("torn_mid_positions", TORN_MID_POSITIONS)],
)
def test_every_torn_write_shape_is_recoverable(name: str, data: str) -> None:
    """A process killed mid-write can stop inside the force block or inside the positions
    card. Both are the same event — a torn tail behind good steps — so both carry the
    recoverable hint and recover to the same two good frames."""
    assert _recover(data).canonical.frame_count == 2


def test_without_a_preset_the_corrupt_file_is_refused() -> None:
    """Refusal is the default (Part 4 §4). Silently keeping the prefix would be the engine
    deciding, on the user's behalf, that the lost tail did not matter."""
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, TORN_MID_FORCES.encode(), filename="pw.out")
    issue = exc.value.issues[0]
    assert issue.code == "QEOUT_TRUNCATED"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"


def test_abort_is_an_explicit_give_up() -> None:
    with pytest.raises(ParseError):
        _recover(TORN_MID_FORCES, {"truncate_corrupt_tail": {"choice": "abort"}})


def test_the_kept_steps_are_the_genuine_ones() -> None:
    obj = _recover(TORN_MID_FORCES).canonical
    assert [f.index for f in obj.frames] == [0, 1]
    energies = []
    for f in obj.frames:
        assert f.electronic.total_energy is not None  # the `!` energy line is always read (P3)
        energies.append(round(f.electronic.total_energy, 8))
    assert energies == [
        round(-49.12345678 * 13.605693122994, 8),
        round(-49.12567890 * 13.605693122994, 8),
    ]
    assert obj.frames[0].atoms.positions[0].tolist() == pytest.approx([2.5, 2.5, 2.5])


def test_the_truncation_is_recorded_as_an_assumption() -> None:
    assumption = _recover(TORN_MID_FORCES).assumptions[0]
    assert assumption.scenario == "truncate_corrupt_tail"
    assert assumption.choice == "truncate"
    assert assumption.parameters["kept_frames"] == 2
    assert "discarded the corrupt tail" in assumption.description


def test_the_dropped_tail_is_recorded_as_removed() -> None:
    """Selective-reductive, not fabricative: the steps that survive are genuine source data,
    so the tail is `removed` and nothing is `supplied`."""
    assumption = _recover(TORN_MID_FORCES).assumptions[0]
    assert [d.path for d in assumption.removed] == ["atoms.positions"]
    assert assumption.supplied == []


def test_a_warning_records_the_truncation_on_the_parse_result() -> None:
    assert "QEOUT_TRUNCATED" in {i.code for i in _recover(TORN_MID_FORCES).issues}


def test_truncating_to_nothing_is_not_a_recovery() -> None:
    """No valid prefix means the honest answer is still the original error (the `yielded == 0`
    guard) — never an empty frame list escaping the §5 contract into a raw pydantic error."""
    with pytest.raises(ParseError) as exc:
        _recover(FIRST_STEP_TORN)
    assert exc.value.issues[0].code == "QEOUT_TRUNCATED"


def test_a_structurally_wrong_step_is_not_truncated_away() -> None:
    """The guard that keeps truncate-mode honest: only errors the parser marked *recoverable*
    end the stream. A force block with more rows than the header declares is not a torn tail —
    it is wrong — so `truncate` must not quietly convert it into a short, plausible-looking
    trajectory."""
    with pytest.raises(ParseError) as exc:
        _recover(INCONSISTENT)
    assert exc.value.issues[0].code == "QEOUT_INCONSISTENT_STEP"


def test_an_intact_file_needs_no_recovery_and_invents_no_truncation() -> None:
    """A *genuinely* intact run (the one that reached pw.x's 'JOB DONE.' sentinel) needs no
    recovery and invents no truncation — QEOUT-C1: the completion sentinel is exactly what
    marks the file whole, and only then is the last frame emitted complete."""
    result = _recover(_FULL)
    assert result.canonical.frame_count == 3
    assert result.assumptions == []
    assert "QEOUT_TRUNCATED" not in {i.code for i in result.issues}


def test_a_clean_boundary_cut_lacking_job_done_is_not_accepted_as_complete() -> None:
    """The QEOUT-C1 gap: ``_GOOD`` ends at a clean line boundary (after step 2's positions
    card) with **no** 'JOB DONE.', so a run killed there must not be read as a complete
    2-frame run — the pending final frame would pair its real energy with a geometry the run
    was never verified to finish. It is refused by default and, under the explicit truncate
    choice, keeps only the steps the stream acknowledged before the incomplete tail."""
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, _GOOD.encode(), filename="pw.out")
    issue = exc.value.issues[0]
    assert issue.code == "QEOUT_TRUNCATED"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"
    kept = _recover(_GOOD).canonical
    assert [f.index for f in kept.frames] == [0]  # step 1 acknowledged; step 2 is the torn tail
    assert "QEOUT_TRUNCATED" in {i.code for i in _recover(_GOOD).issues}


def test_a_run_cut_after_the_last_energy_line_before_its_blocks_recovers_to_the_prefix() -> None:
    """The slice-plan shape: a 3-step run cut after step 3's '!    total energy' line but
    before its force block. Step 3's frame is never emitted — no real-energy/arbitrary-
    geometry 3rd frame — and truncation keeps the two acknowledged steps."""
    torn = _FULL[: _FULL.index("     Forces acting on atoms", _STEP3)]
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, torn.encode(), filename="pw.out")
    assert exc.value.issues[0].code == "QEOUT_TRUNCATED"
    kept = _recover(torn).canonical
    assert [f.index for f in kept.frames] == [0, 1]
    # The torn third frame must never carry step 3's energy with a geometry that is not its
    # own — under the old behavior frame 2 would have paired -49.13012345 Ry with the initial
    # 2.49… positions. Now that geometry is simply refused.
    assert all(f.electronic.total_energy is not None for f in kept.frames)
    assert kept.frames[1].atoms.positions[0].tolist() == pytest.approx([2.48, 2.5, 2.5])


def test_recovery_keeps_the_prefix_lazily() -> None:
    """The recovery must not give up the streaming property it exists to serve: the good steps
    are yielded one at a time, so a torn 10⁴-step file recovers with one step resident."""
    stream = make_qe_pw_out_parser().parse_stream(
        io.BytesIO(TORN_MID_FORCES.encode()), filename="pw.out", truncate=True
    )
    frames = stream.frames()
    assert next(frames).frame.index == 0
    assert next(frames).frame.index == 1
    with pytest.raises(StopIteration):
        next(frames)
    assert "QEOUT_TRUNCATED" in {i.code for i in stream.issues}


# --- the hint routes end-to-end with no new recovery scenario (done-means #2) ----------


def test_the_hint_maps_to_the_existing_scenario() -> None:
    """`truncate_at_last_valid_frame` → `truncate_corrupt_tail` is the shared mapping
    (`conversion.parse_recovery`); qe_pw_out raises the hinted error and implements
    parse_recover — nothing new was added for the QE format (D197)."""
    from xtalate.conversion.parse_recovery import _HINT_TO_SCENARIO

    assert _HINT_TO_SCENARIO["truncate_at_last_valid_frame"] == "truncate_corrupt_tail"


# --- the CLI surface (done-means #1) --------------------------------------------------


def test_cli_refuses_without_a_preset_and_recovers_with_one(tmp_path: Path) -> None:
    """`convert` refuses a torn pw.out without a preset; `--recover
    truncate_corrupt_tail=truncate` completes keeping the valid prefix."""
    src = tmp_path / "pw.out"
    src.write_text(TORN_MID_FORCES)

    # No preset: the recoverable parse error stands (refusal is the default).
    out = tmp_path / "out.extxyz"
    assert main(["convert", str(src), "--to", "extxyz", "-o", str(out)]) == EXIT_PARSE_ERROR
    assert not out.exists()

    # With the preset: completes and writes the kept prefix.
    assert (
        main(
            [
                "convert",
                str(src),
                "--to",
                "extxyz",
                "-o",
                str(out),
                "--recover",
                "truncate_corrupt_tail=truncate",
            ]
        )
        == EXIT_OK
    )
    assert out.is_file() and out.stat().st_size > 0
