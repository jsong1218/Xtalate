"""Partial occupancy must be *warned about*, not merely dropped (M19, Part 3 §3 n.11).

Occupancy is the Canonical Model's one named gap. The CIF parser carries the column verbatim
under ``user_metadata.custom_per_atom['cif:occupancy']`` and warns at parse time (M19 slice 1),
but a parse warning is about the *file we read*. This is the other half: a warning about the
*file we write*. No Phase 1 target can express fractional occupancy, and a site written without
one reads as fully occupied — so the output asserts a structure the source never described. The
ordinary ``removed`` entry for ``user_metadata.custom_per_atom`` says an annotation was not
carried; it does not say the physical claim changed. This warning does (**P4**, **P5**).

The gate is a capability declaration, never a format list, so a format that *represents* occupancy
silences the warning by naming the key (**P6**). Merely being able to carry the numbers is not
enough — see ``test_verbatim_carriage_is_not_representation``.
"""

from __future__ import annotations

import io

import pytest

from xtalate.conversion import ConversionEngine
from xtalate.conversion.preflight import build_preflight, partial_occupancy_count
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.schema.paths import OCCUPANCY_CUSTOM_KEY

_REGISTRY = default_registry()
_WARNING_CODE = "PARTIAL_OCCUPANCY_NOT_REPRESENTED"

# Every Phase 1 target. None of them can express occupancy, so every one must warn.
_TARGETS = ["xyz", "extxyz", "poscar", "contcar", "xdatcar", "ase_traj"]

_CIF_TEMPLATE = """data_occupancy_case
_cell_length_a     4.0
_cell_length_b     4.0
_cell_length_c     4.0
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma  90.0
_space_group_name_H-M_alt 'P 1'
loop_
_space_group_symop_operation_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1  Na  0.0   0.0   0.0   {first}
Cl1  Cl  0.5   0.5   0.5   {second}
"""

_NO_OCCUPANCY_CIF = """data_no_occupancy
_cell_length_a     4.0
_cell_length_b     4.0
_cell_length_c     4.0
_cell_angle_alpha  90.0
_cell_angle_beta   90.0
_cell_angle_gamma  90.0
_space_group_name_H-M_alt 'P 1'
loop_
_space_group_symop_operation_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1  Na  0.0   0.0   0.0
Cl1  Cl  0.5   0.5   0.5
"""


def _parse(text: str) -> CanonicalObject:
    return (
        _REGISTRY.get_parser("cif").parse(io.BytesIO(text.encode()), filename="case.cif").canonical
    )


def _occupancies(first: str, second: str) -> CanonicalObject:
    return _parse(_CIF_TEMPLATE.format(first=first, second=second))


def _warning_codes(source: CanonicalObject, target: str) -> list[str]:
    diff = build_preflight(source, _REGISTRY.capability_matrix(), target)
    return [w.code for w in diff.warnings]


# --------------------------------------------------------------------------------------------
# partial_occupancy_count: the scalar both conversion paths derive
# --------------------------------------------------------------------------------------------


def test_count_is_zero_when_no_occupancy_is_declared() -> None:
    # Absence of the column is not a claim of partial occupancy (P3) — and not a claim of full
    # occupancy either; there is simply nothing here that a target would fail to represent.
    assert partial_occupancy_count({}) == 0


def test_count_is_zero_when_every_site_is_fully_occupied() -> None:
    assert partial_occupancy_count({OCCUPANCY_CUSTOM_KEY: [1.0, 1.0]}) == 0


def test_count_reports_how_many_sites_are_partial() -> None:
    assert partial_occupancy_count({OCCUPANCY_CUSTOM_KEY: [1.0, 0.5, 0.25]}) == 2


def test_unknown_occupancy_counts_as_partial() -> None:
    # '?' / '.' arrives as None. It is not a statement of full occupancy, so writing the site out
    # bare would turn the source's silence into an assertion (P4) — exactly what the warning is for.
    assert partial_occupancy_count({OCCUPANCY_CUSTOM_KEY: [1.0, None]}) == 1


def test_non_numeric_occupancy_counts_as_partial() -> None:
    # A column that is not wholly numeric stays as source strings; '1.0' still reads as full,
    # anything unparseable is not a statement we can accept as full.
    assert partial_occupancy_count({OCCUPANCY_CUSTOM_KEY: ["1.0", "half"]}) == 1


def test_count_ignores_other_custom_per_atom_keys() -> None:
    assert partial_occupancy_count({"cif:wyckoff_symbol": ["a", "b"]}) == 0


# --------------------------------------------------------------------------------------------
# The warning in the pre-flight diff
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", _TARGETS)
def test_partial_occupancy_warns_for_every_phase_1_target(target: str) -> None:
    # The M19 go/no-go checkpoint: "structures with occupancy != 1.0 additionally surface a
    # Conversion Report warning for every target".
    source = _occupancies("0.5", "1.0")
    assert _WARNING_CODE in _warning_codes(source, target)


@pytest.mark.parametrize("target", _TARGETS)
def test_full_occupancy_does_not_warn(target: str) -> None:
    # A file that says every site is fully occupied loses nothing physical when the column is
    # dropped: the output asserts what the source asserted. Warning here would be noise.
    source = _occupancies("1.0", "1.0")
    assert _WARNING_CODE not in _warning_codes(source, target)


@pytest.mark.parametrize("target", _TARGETS)
def test_absent_occupancy_does_not_warn(target: str) -> None:
    source = _parse(_NO_OCCUPANCY_CIF)
    assert _WARNING_CODE not in _warning_codes(source, target)


def test_unknown_occupancy_warns() -> None:
    source = _occupancies("?", "1.0")
    assert _WARNING_CODE in _warning_codes(source, "poscar")


def test_warning_names_the_count_and_the_target() -> None:
    source = _occupancies("0.5", "0.25")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "poscar")
    message = next(w.message for w in diff.warnings if w.code == _WARNING_CODE)
    assert "2 atom(s)" in message
    assert "poscar" in message


def test_warning_is_capability_sourced() -> None:
    # It is a statement about what the *target* cannot hold, not about what the source file said —
    # the parse-side occupancy warning (M19 slice 1) is the `parse`-sourced one.
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "poscar")
    assert next(w.source for w in diff.warnings if w.code == _WARNING_CODE) == "capability"


def test_warning_accompanies_rather_than_replaces_the_removed_entry() -> None:
    # Both, always: `removed` is the accounting (the container was not carried), the warning is the
    # consequence (the structure written differs). Neither alone tells the whole truth (P5).
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "poscar")
    removed = {e.path for e in diff.removed}
    assert any(p.startswith("user_metadata.custom_per_atom") for p in removed)
    assert _WARNING_CODE in [w.code for w in diff.warnings]


# --------------------------------------------------------------------------------------------
# The warning in the Conversion Report
# --------------------------------------------------------------------------------------------


def test_verbatim_carriage_is_not_representation() -> None:
    # extXYZ writes arbitrary per-atom columns, so the occupancy numbers survive the conversion —
    # and the warning fires anyway. An unlabelled extra column is not occupancy: no reader of the
    # output treats those numbers as site occupancies, so the structure the file describes is still
    # fully occupied. Carrying the bytes is not the same as representing the quantity.
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "extxyz")
    preserved = {e.path for e in diff.preserved}
    assert f"user_metadata.custom_per_atom[{OCCUPANCY_CUSTOM_KEY!r}]" in preserved
    assert _WARNING_CODE in [w.code for w in diff.warnings]


def test_naming_the_key_suppresses_the_warning() -> None:
    # The P6 escape hatch, exercised against a stand-in: a format that declares it handles
    # 'cif:occupancy' specifically silences this with no edit to the pre-flight diff. When the
    # CIF exporter lands (or occupancy is promoted to a canonical field), this is the mechanism.
    from xtalate.capabilities import Registry
    from xtalate.exporters import builtin_exporters
    from xtalate.parsers import builtin_parsers
    from xtalate.sdk import CapabilityLevel, FieldCapability, FormatCapabilities

    poscar_cls = type(_REGISTRY.get_exporter("poscar"))

    class OccupancyAwareExporter(poscar_cls):  # type: ignore[misc, valid-type]
        def capabilities(self) -> FormatCapabilities:
            base = super().capabilities()
            fields = dict(base.fields)
            fields["user_metadata.custom_per_atom"] = FieldCapability(
                level=CapabilityLevel.FULL, notes="Stub target that stores site occupancy."
            )
            return base.model_copy(
                update={
                    "format_id": self.format_id,
                    "fields": fields,
                    "writable_custom_keys": {
                        "user_metadata.custom_per_atom": [OCCUPANCY_CUSTOM_KEY]
                    },
                }
            )

    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    reg.register_exporter(OccupancyAwareExporter(format_id="occupancy_aware_stub"))

    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, reg.capability_matrix(), "occupancy_aware_stub")
    assert _WARNING_CODE not in [w.code for w in diff.warnings]


def test_warning_reaches_the_conversion_report() -> None:
    # The deliverable is about the *report*, not the diff: this is what a user actually sees.
    result = ConversionEngine(_REGISTRY).convert(
        _occupancies("0.5", "1.0"),
        source_format_id="cif",
        target_format_id="poscar",
        mode="permissive",
    )
    assert _WARNING_CODE in [w.code for w in result.report.warnings]


def test_warning_survives_a_strict_acknowledged_conversion() -> None:
    # Acknowledging loss accepts that data is dropped; it does not make the physical claim go away.
    result = ConversionEngine(_REGISTRY).convert(
        _occupancies("0.5", "1.0"),
        source_format_id="cif",
        target_format_id="poscar",
        mode="strict",
        acknowledge_loss=True,
    )
    assert result.report.status == "completed"
    assert _WARNING_CODE in [w.code for w in result.report.warnings]
