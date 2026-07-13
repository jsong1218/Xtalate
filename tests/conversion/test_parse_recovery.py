"""Parse-time recovery tests (Slice 2, MASTER_SPEC Part 4 §3.3, parse-time scenarios).

Covers the two scenarios that fire before a Canonical Object exists — ``missing_species`` (a
VASP-4 POSCAR with no species line) and ``truncate_corrupt_tail`` (a trajectory with a corrupt
final frame) — through the parser ``parse_recover`` hook and the ``parse_with_recovery``
orchestration, and their threading into the Conversion Report by ``ConversionEngine.convert``.
"""

from __future__ import annotations

import pytest

from xtalate.conversion import ConversionEngine, parse_with_recovery
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

# A VASP-4 POSCAR: atom counts, no species line (recovery_hint="supply_species").
_VASP4 = b"""vasp4
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
2 1
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
  0.25 0.25 0.25
"""

# A VASP-5 reference (species + counts) matching the VASP-4 file's 2+1 grouping, for
# missing_species upload_reference.
_REF_V5 = b"""ref
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H O
2 1
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
  0.25 0.25 0.25
"""

# A 3-frame XYZ trajectory whose final frame is truncated mid-coordinates.
_CORRUPT_XYZ = b"2\nf0\nH 0 0 0\nH 0 0 0.8\n2\nf1\nH 0 0 0\nH 0 0 0.9\n2\nf2\nH 0 0 0\n"


def _reg():  # type: ignore[no-untyped-def]
    return default_registry()


# --- missing_species (fabricative, parse-time) ---------------------------------------------------


def test_missing_species_refuses_without_a_preset() -> None:
    # No preset for the recoverable error → the ParseError stands (refusal is the default).
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_reg(), _VASP4, filename="POSCAR")
    assert exc.value.issues[0].recovery_hint == "supply_species"


def test_missing_species_species_map_supplies_symbols() -> None:
    pr = parse_with_recovery(
        _reg(),
        _VASP4,
        filename="POSCAR",
        recovery_choices={
            "missing_species": {"choice": "species_map", "parameters": {"species": "H:O"}}
        },
    )
    assert list(pr.canonical.frames[0].atoms.symbols) == ["H", "H", "O"]
    (assumption,) = pr.assumptions
    assert assumption.scenario == "missing_species"
    assert assumption.choice == "species_map"
    # Fabricative: symbols were absent from the file, so they are a SuppliedField.
    assert [s.path for s in assumption.supplied] == ["atoms.symbols"]
    assert any(i.code == "POSCAR_SPECIES_SUPPLIED" for i in pr.issues)


def test_missing_species_upload_reference_reads_symbols_from_a_matching_structure() -> None:
    ref = parse_with_recovery(_reg(), _REF_V5, filename="POSCAR").canonical
    pr = parse_with_recovery(
        _reg(),
        _VASP4,
        filename="POSCAR",
        recovery_choices={
            "missing_species": {"choice": "upload_reference", "parameters": {"reference": ref}}
        },
    )
    assert list(pr.canonical.frames[0].atoms.symbols) == ["H", "H", "O"]


def test_missing_species_threads_into_the_conversion_report() -> None:
    # End to end: the parse-time Assumption lands in the final report; atoms.symbols is `supplied`
    # (fabricated), never `preserved`, and the completeness invariant still holds.
    reg = _reg()
    pr = parse_with_recovery(
        reg,
        _VASP4,
        filename="POSCAR",
        recovery_choices={
            "missing_species": {"choice": "species_map", "parameters": {"species": "H:O"}}
        },
    )
    result = ConversionEngine(reg).convert(
        pr.canonical, source_format_id=pr.format_id, target_format_id="poscar", parse_recovery=pr
    )
    assert result.report.status == "completed"
    assert "atoms.symbols" in {s.path for s in result.report.supplied}
    assert "atoms.symbols" not in {e.path for e in result.report.preserved}
    (assumption,) = result.report.assumptions
    assert assumption.id == "A1" and assumption.scenario == "missing_species"
    assert result.validation is not None and result.validation.status in (
        "passed",
        "passed_with_warnings",
    )


def test_missing_species_unoffered_choice_is_a_caller_error() -> None:
    from xtalate.recovery import RecoveryError

    with pytest.raises(RecoveryError, match="not an offered option"):
        parse_with_recovery(
            _reg(),
            _VASP4,
            filename="POSCAR",
            recovery_choices={"missing_species": {"choice": "guess"}},
        )


# --- truncate_corrupt_tail (selective-reductive, parse-time) --------------------------------------


def test_truncate_refuses_without_a_preset() -> None:
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_reg(), _CORRUPT_XYZ, filename="t.xyz")
    assert exc.value.issues[0].recovery_hint == "truncate_at_last_valid_frame"


def test_truncate_keeps_the_valid_prefix() -> None:
    pr = parse_with_recovery(
        _reg(),
        _CORRUPT_XYZ,
        filename="t.xyz",
        recovery_choices={"truncate_corrupt_tail": {"choice": "truncate"}},
    )
    assert pr.canonical.frame_count == 2  # the two valid frames, corrupt third dropped
    (assumption,) = pr.assumptions
    assert assumption.scenario == "truncate_corrupt_tail"
    assert assumption.choice == "truncate"
    # Selective-reductive: a removed entry, no supplied field (kept frames are genuine).
    assert assumption.supplied == []
    assert [d.path for d in assumption.removed] == ["atoms.positions"]
    assert any(i.code == "XYZ_TRUNCATED" for i in pr.issues)


def test_truncate_abort_re_raises_the_parse_error() -> None:
    # `abort` is an explicit give-up — the recoverable error stands (Part 4 §3.3).
    with pytest.raises(ParseError):
        parse_with_recovery(
            _reg(),
            _CORRUPT_XYZ,
            filename="t.xyz",
            recovery_choices={"truncate_corrupt_tail": {"choice": "abort"}},
        )


def test_truncate_threads_removed_frames_into_the_report() -> None:
    reg = _reg()
    pr = parse_with_recovery(
        reg,
        _CORRUPT_XYZ,
        filename="t.xyz",
        recovery_choices={"truncate_corrupt_tail": {"choice": "truncate"}},
    )
    result = ConversionEngine(reg).convert(
        pr.canonical, source_format_id=pr.format_id, target_format_id="xyz", parse_recovery=pr
    )
    assert result.report.status == "completed"
    assert "atoms.positions" in {e.path for e in result.report.removed}
    (assumption,) = result.report.assumptions
    assert assumption.scenario == "truncate_corrupt_tail"
    assert result.canonical_out is not None and result.canonical_out.frame_count == 2


# --- a clean file never triggers recovery --------------------------------------------------------


def test_clean_parse_carries_no_assumptions() -> None:
    clean = b"2\nf0\nH 0 0 0\nH 0 0 0.8\n"
    pr = parse_with_recovery(_reg(), clean, filename="t.xyz")
    assert pr.assumptions == []
    assert pr.canonical.frame_count == 1
