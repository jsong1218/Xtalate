"""``truncate_at_last_valid_frame`` recovery on the OUTCAR reader (v1.2 M43-S3; DECISIONS.md D166).

The OUTCAR counterpart of XDATCAR's torn-tail recovery (M13/D56): a run killed while writing ionic
step *k* leaves steps 0..k-1 as perfectly good science behind a corrupt tail. Keeping that prefix is
the **user's** explicit choice, never the parser's — without a preset the corrupt file is refused;
with one, the kept steps and the dropped tail are both recorded (P1, P4). No new recovery machinery:
the shared ``truncate_corrupt_tail`` scenario (Revision 1.15) is reused verbatim — OUTCAR wires into
it by raising the hinted ``OUTCAR_TRUNCATED`` error and implementing ``parse_recover``.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, main
from xtalate.conversion.parse_recovery import ParseRecovery, parse_with_recovery
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

_REGISTRY = default_registry()
_TRUNCATE: dict[str, dict[str, object]] = {"truncate_corrupt_tail": {"choice": "truncate"}}

_HEADER = """\
 vasp.6.3.2 08Feb23 (build Aug 08 2023 12:00:00) complex

  POTCAR:    PAW_PBE H 15Jun2001
    VRHFIN =H: 1s1
  POTCAR:    PAW_PBE O 15Jun2001
    VRHFIN =O: 2s2p4

  ions per type =               2   1

  NIONS =       3

  direct lattice vectors                 reciprocal lattice vectors
     10.000000000  0.000000000  0.000000000     0.100000000  0.000000000  0.000000000
      0.000000000 10.000000000  0.000000000     0.000000000  0.100000000  0.000000000
      0.000000000  0.000000000 10.000000000     0.000000000  0.000000000  0.100000000

"""


def _step(n: int, energy: float) -> str:
    # Real VASP order: the POSITION/TOTAL-FORCE table, then the energy(sigma->0) summary.
    return f"""\
 ---------------------------------- Iteration {n}( {n}) ---------------------------------

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.50000000   5.00000000   0.20000000  -0.10000000  0.00000000
      7.50000000   5.00000000   5.00000000   -0.10000000  0.05000000  0.00000000
      5.00000000   5.00000000   5.00000000   -0.10000000  0.00000000  0.05000000
  -----------------------------------------------------------------------------
     total drift:                                0.00000000   0.00000000   0.00000000

  FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)
    energy  without entropy=       {energy:.8f}  energy(sigma->0) =       {energy:.8f}
"""


def _step_table_only(n: int) -> str:
    # A step whose force table is complete but whose energy(sigma->0) summary was never written —
    # the run died in the gap after the forces, before the FREE ENERGIE block (real VASP order).
    return f"""\
 ---------------------------------- Iteration {n}( {n}) ---------------------------------

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.40000000   5.00000000   0.01000000  -0.01000000  0.00000000
      7.40000000   5.00000000   5.00000000   -0.01000000  0.00500000  0.00000000
      5.00000000   5.00000000   5.00000000   -0.01000000  0.00000000  0.00500000
  -----------------------------------------------------------------------------
     total drift:                                0.00000000   0.00000000   0.00000000
"""


_GOOD = _step(1, -76.4) + _step(2, -76.41)

#: Step 3's force table was written in full, then the process died before its energy(sigma->0)
#: summary — the torn-after-table shape (a complete VASP step always ends with the summary).
TORN_AFTER_TABLE = _HEADER + _GOOD + _step_table_only(3)

#: Step 3's force table stopped after one of its three rows.
TORN_TABLE = (
    _HEADER
    + _GOOD
    + """\
 ----------------------------------- Iteration   3(   3)  ---------------------------------------

  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.40000000   5.00000000   0.01000000  -0.01000000  0.00000000
"""
)

#: The very first table is torn: there is no valid prefix to keep.
FIRST_TABLE_TORN = (
    _HEADER
    + """\
  -----------------------------------------------------------------------------
    POSITION                                       TOTAL-FORCE (eV/Angst)
  -----------------------------------------------------------------------------
      5.00000000   7.50000000   5.00000000   0.20000000  -0.10000000  0.00000000
"""
)

_EXTRA_ROW = "      5.00000000   7.40000000   5.00000000   0.01000000  -0.01000000  0.00000000\n"

#: Two good steps, then a step whose table carries a 4th row — a structural inconsistency, not a
#: torn tail, so `truncate` must not quietly turn it into a plausible 2-frame trajectory.
INCONSISTENT = (
    _HEADER
    + _GOOD
    + _step(3, -76.42).replace(
        "  -----------------------------------------------------------------------------\n"
        "     total drift:",
        _EXTRA_ROW
        + "  -----------------------------------------------------------------------------\n"
        + "     total drift:",
    )
)


def _recover(data: str, choices: dict[str, dict[str, object]] | None = None) -> ParseRecovery:
    return parse_with_recovery(
        _REGISTRY, data.encode(), filename="OUTCAR", recovery_choices=choices or _TRUNCATE
    )


@pytest.mark.parametrize(
    ("name", "data"),
    [("torn_after_table", TORN_AFTER_TABLE), ("torn_table", TORN_TABLE)],
)
def test_every_torn_write_shape_is_recoverable(name: str, data: str) -> None:
    """A process killed mid-write can stop after a complete force table but before its
    energy(sigma->0) summary, or partway through the force table itself. Both are the same event —
    a torn tail behind good steps — so both carry the recoverable hint."""
    assert _recover(data).canonical.frame_count == 2


def test_without_a_preset_the_corrupt_file_is_refused() -> None:
    """Refusal is the default (Part 4 §4). Silently keeping the prefix would be the engine deciding,
    on the user's behalf, that the lost tail did not matter."""
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, TORN_TABLE.encode(), filename="OUTCAR")
    issue = exc.value.issues[0]
    assert issue.code == "OUTCAR_TRUNCATED"
    assert issue.recovery_hint == "truncate_at_last_valid_frame"


def test_abort_is_an_explicit_give_up() -> None:
    with pytest.raises(ParseError):
        _recover(TORN_TABLE, {"truncate_corrupt_tail": {"choice": "abort"}})


def test_the_kept_steps_are_the_genuine_ones() -> None:
    obj = _recover(TORN_TABLE).canonical
    assert [f.index for f in obj.frames] == [0, 1]
    assert [f.electronic.total_energy for f in obj.frames] == [-76.4, -76.41]
    assert obj.frames[0].atoms.positions[0].tolist() == [5.0, 7.5, 5.0]


def test_the_truncation_is_recorded_as_an_assumption() -> None:
    assumption = _recover(TORN_TABLE).assumptions[0]
    assert assumption.scenario == "truncate_corrupt_tail"
    assert assumption.choice == "truncate"
    assert assumption.parameters["kept_frames"] == 2
    assert "discarded the corrupt tail" in assumption.description


def test_the_dropped_tail_is_recorded_as_removed() -> None:
    """Selective-reductive, not fabricative: the steps that survive are genuine source data, so the
    tail is `removed` and nothing is `supplied`."""
    assumption = _recover(TORN_TABLE).assumptions[0]
    assert [d.path for d in assumption.removed] == ["atoms.positions"]
    assert assumption.supplied == []


def test_a_warning_records_the_truncation_on_the_parse_result() -> None:
    assert "OUTCAR_TRUNCATED" in {i.code for i in _recover(TORN_TABLE).issues}


def test_truncating_to_nothing_is_not_a_recovery() -> None:
    """No valid prefix means the honest answer is still the original error (the `yielded == 0`
    guard) — never an empty frame list escaping the §5 contract into a raw pydantic error."""
    with pytest.raises(ParseError) as exc:
        _recover(FIRST_TABLE_TORN)
    assert exc.value.issues[0].code == "OUTCAR_TRUNCATED"


def test_a_structurally_wrong_step_is_not_truncated_away() -> None:
    """The guard that keeps truncate-mode honest: only errors the parser marked *recoverable* end
    the stream. A table with more atoms than the header declares is not a torn tail — it is wrong —
    so `truncate` must not quietly convert it into a short, plausible-looking trajectory."""
    with pytest.raises(ParseError) as exc:
        _recover(INCONSISTENT)
    assert exc.value.issues[0].code == "OUTCAR_INCONSISTENT_STEP"


def test_an_intact_file_needs_no_recovery_and_invents_no_truncation() -> None:
    result = _recover(_HEADER + _GOOD)
    assert result.canonical.frame_count == 2
    assert result.assumptions == []
    assert "OUTCAR_TRUNCATED" not in {i.code for i in result.issues}


def test_recovery_keeps_the_prefix_lazily() -> None:
    """The recovery must not give up the streaming property it exists to serve: the good steps are
    yielded one at a time, so a torn 10⁴-step file recovers with one step resident."""
    stream = make_outcar_parser().parse_stream(
        io.BytesIO(TORN_TABLE.encode()), filename="OUTCAR", truncate=True
    )
    frames = stream.frames()
    assert next(frames).frame.index == 0
    assert next(frames).frame.index == 1
    with pytest.raises(StopIteration):
        next(frames)
    assert "OUTCAR_TRUNCATED" in {i.code for i in stream.issues}


# --- the CLI surface (done-means #1) ------------------------------------------------


def test_cli_refuses_without_a_preset_and_recovers_with_one(tmp_path: Path) -> None:
    """`convert` refuses a torn OUTCAR without a preset; `--recover
    truncate_corrupt_tail=truncate` completes keeping the valid prefix."""
    src = tmp_path / "OUTCAR"
    src.write_text(TORN_TABLE)

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
