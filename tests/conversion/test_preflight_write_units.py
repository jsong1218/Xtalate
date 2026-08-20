"""Write-side `ambiguous_units` tests (v1.3 M47-S1, D177; Part 4 §3.3).

The export-time twin of M46's parse-time trigger: a LAMMPS target defines no units, so every
write to it must *declare* the unit style the values are written in. The pre-flight fires the
same `ambiguous_units` scenario — keyed on **target identity** (the declared
``requires_units_style`` capability), not on any source carry — refusing without a preset;
with a preset the resolved style threads through the recovery engine to the exporter
(``custom_global['lammps_dump:units']``), which writes the ``ITEM: UNITS`` header and
converts, and the write validates because the re-parse reproduces the choice.
"""

from __future__ import annotations

import io

import pytest

from xtalate.conversion import ConversionEngine
from xtalate.parsers.lammps_dump import make_lammps_dump_parser
from xtalate.parsers.poscar import make_poscar_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

_POSCAR = b"""nacl primitive
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
Na Cl
1 1
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5
"""

DUMP = b"""ITEM: UNITS
metal
ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS p p p
0 20
0 20
0 20
ITEM: ATOMS id element x y z
1 Si 1.0 2.0 3.0
2 O 4.0 5.0 6.0
"""

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)


@pytest.fixture()
def poscar_source() -> CanonicalObject:
    return make_poscar_parser().parse(io.BytesIO(_POSCAR), filename=None).canonical


@pytest.fixture()
def dump_source() -> CanonicalObject:
    return make_lammps_dump_parser().parse(io.BytesIO(DUMP), filename=None).canonical


def test_preflight_draft_shows_the_target_driven_scenario(poscar_source: CanonicalObject) -> None:
    # The draft report's status is the pause signal; the *offered choices* are exposed through
    # the Recovery Preview (the same pre-flight diff), which names the scenario and its
    # honest, pair-specific option list (Part 4 §3.3).
    draft = _ENGINE.preflight(
        poscar_source,
        source_format_id="poscar",
        target_format_id="lammps_dump",
    )
    assert draft.status == "awaiting_recovery"
    preview = _ENGINE.preview_recovery(
        poscar_source, source_format_id="poscar", target_format_id="lammps_dump"
    )
    assert {s.scenario for s in preview.unresolved} == {"ambiguous_units"}
    units = next(s for s in preview.unresolved if s.scenario == "ambiguous_units")
    assert units.options == ["metal", "real", "si"]


def test_convert_refuses_without_a_unit_preset(poscar_source: CanonicalObject) -> None:
    result = _ENGINE.convert(
        poscar_source, source_format_id="poscar", target_format_id="lammps_dump"
    )
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert [s["scenario"] for s in scenarios] == ["ambiguous_units"]
    assert scenarios[0]["options"] == ["metal", "real", "si"]


def test_convert_with_metal_preset_writes_header_assumption_and_validates(
    poscar_source: CanonicalObject,
) -> None:
    result = _ENGINE.convert(
        poscar_source,
        source_format_id="poscar",
        target_format_id="lammps_dump",
        recovery_choices={"ambiguous_units": {"choice": "metal", "parameters": {}}},
    )
    assert result.report.status == "completed"
    # The interpretive Assumption: recorded, no `supplied` entry (nothing fabricated), the
    # style stated in plain language alongside the option's unit basis.
    assumptions = result.report.assumptions
    assert [a.scenario for a in assumptions] == ["ambiguous_units"]
    assert assumptions[0].choice == "metal"
    assert assumptions[0].parameters == {"unit_style": "metal"}
    assert "Å, ps, eV" in assumptions[0].description
    assert result.report.supplied == []
    # The ITEM: UNITS header is written and the engine's own validation passes (the re-parse
    # reproduces the declared style, so the metadata check is faithful).
    assert result.output is not None
    assert b"ITEM: UNITS\nmetal" in result.output
    assert result.validation is not None
    assert result.validation.status == "passed"
    # The resolved style rode the object channel to the exporter: canonical_out carries it.
    assert result.canonical_out is not None
    assert result.canonical_out.user_metadata.custom_global["lammps_dump:units"] == "metal"


def test_recovered_style_overrides_a_carried_source_style(dump_source: CanonicalObject) -> None:
    """Even a dump source whose file *declared* metal must be re-resolved on write (target
    identity — a dump always needs a style): the user's preset wins, and the output states it."""
    assert dump_source.user_metadata.custom_global["lammps_dump:units"] == "metal"
    result = _ENGINE.convert(
        dump_source,
        source_format_id="lammps_dump",
        target_format_id="lammps_dump",
        recovery_choices={"ambiguous_units": {"choice": "si", "parameters": {}}},
    )
    assert result.report.status == "completed"
    assert result.output is not None
    assert b"ITEM: UNITS\nsi" in result.output
    assert result.validation is not None
    assert result.validation.status == "passed"


def test_non_lammps_target_never_fires(dump_source: CanonicalObject) -> None:
    # A dump → extXYZ write needs no units style (extXYZ is unit-free by convention-less
    # design); the source's declared-style carry is a readable provenance note, not a trigger.
    preview = _ENGINE.preview_recovery(
        dump_source, source_format_id="lammps_dump", target_format_id="extxyz"
    )
    assert all(s.scenario != "ambiguous_units" for s in preview.unresolved)


def test_dump_as_target_is_not_streaming_eligible() -> None:
    """Reconciliation 3: the write needs a static recovery choice (the units style, known
    before any frame), so the streaming fast path rejects the pair — convert() serves it."""
    assert _ENGINE.streaming_eligible("poscar", "lammps_dump") is False
    with pytest.raises(ValueError, match="not streaming-eligible"):
        _ENGINE.convert_stream(
            io.BytesIO(_POSCAR),
            source_format_id="poscar",
            target_format_id="lammps_dump",
            output=io.BytesIO(),
        )
