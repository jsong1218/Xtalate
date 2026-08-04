"""Partial occupancy must be *warned about*, not merely dropped (Part 3 §3 n.11; M35).

Occupancy is a first-class canonical field now — ``atoms.occupancies`` (M35). The CIF parser reads
it and warns at parse time when a site is partial, but a parse warning is about the *file we read*.
This is the other half: a warning about the *file we write*. No Phase 1 target but CIF can express
fractional occupancy, and a site written without one reads as fully occupied — so the output
asserts a structure the source never described. The ordinary ``removed`` entry for
``atoms.occupancies`` says the field was not carried; it does not say the physical claim changed.
This warning does (**P4**, **P5**).

The gate is a capability declaration, never a format list, so a format that *represents* occupancy
silences the warning by declaring a writable ``atoms.occupancies`` capability (**P6**) — see
``test_declaring_the_field_writable_suppresses_the_warning``.
"""

from __future__ import annotations

import io

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine
from xtalate.conversion.preflight import build_preflight, partial_occupancy_count
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.sdk import CapabilityLevel, ExporterPlugin, FieldCapability, FormatCapabilities

_REGISTRY = default_registry()
_WARNING_CODE = "PARTIAL_OCCUPANCY_NOT_REPRESENTED"
_OCCUPANCY_PATH = "atoms.occupancies"

# Every Phase 1 target other than CIF. None of them can express occupancy, so every one must warn.
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
# partial_occupancy_count: the scalar the materialized path derives from atoms.occupancies
# --------------------------------------------------------------------------------------------


def test_count_is_zero_when_no_occupancy_is_declared() -> None:
    # Absence of the field is not a claim of partial occupancy (P3) — and not a claim of full
    # occupancy either; there is simply nothing here that a target would fail to represent.
    assert partial_occupancy_count(None) == 0


def test_count_is_zero_when_every_site_is_fully_occupied() -> None:
    assert partial_occupancy_count([1.0, 1.0]) == 0


def test_count_reports_how_many_sites_are_partial() -> None:
    assert partial_occupancy_count([1.0, 0.5, 0.25]) == 2


def test_unknown_occupancy_counts_as_partial() -> None:
    # '?' / '.' arrives as None. It is not a statement of full occupancy, so writing the site out
    # bare would turn the source's silence into an assertion (P4) — exactly what the warning is for.
    assert partial_occupancy_count([1.0, None]) == 1


# --------------------------------------------------------------------------------------------
# The warning in the pre-flight diff
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("target", _TARGETS)
def test_partial_occupancy_warns_for_every_non_cif_target(target: str) -> None:
    # Structures with occupancy != 1.0 surface a Conversion Report warning for every target that
    # cannot represent the first-class occupancy field.
    source = _occupancies("0.5", "1.0")
    assert _WARNING_CODE in _warning_codes(source, target)


@pytest.mark.parametrize("target", _TARGETS)
def test_full_occupancy_does_not_warn(target: str) -> None:
    # A file that says every site is fully occupied loses nothing physical when the field is
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
    # the parse-side CIF_PARTIAL_OCCUPANCY is the `parse`-sourced one.
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "poscar")
    assert next(w.source for w in diff.warnings if w.code == _WARNING_CODE) == "capability"


def test_warning_accompanies_rather_than_replaces_the_removed_entry() -> None:
    # Both, always: `removed` is the accounting (the field was not carried), the warning is the
    # consequence (the structure written differs). Neither alone tells the whole truth (P5).
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, _REGISTRY.capability_matrix(), "poscar")
    assert _OCCUPANCY_PATH in {e.path for e in diff.removed}
    assert _WARNING_CODE in [w.code for w in diff.warnings]


# --------------------------------------------------------------------------------------------
# The P6 gate: a target that *represents* occupancy silences the warning
# --------------------------------------------------------------------------------------------


def _stub_exporter(format_id: str, *, represents_occupancy: bool = False) -> ExporterPlugin:
    """A POSCAR-derived stand-in, optionally declaring that it writes the occupancy field. Merely
    carrying arbitrary per-atom numbers is not enough — only a declared ``atoms.occupancies``
    capability says the format represents the quantity."""
    poscar_cls = type(_REGISTRY.get_exporter("poscar"))

    class StubExporter(poscar_cls):  # type: ignore[misc, valid-type]
        def capabilities(self) -> FormatCapabilities:
            base: FormatCapabilities = super().capabilities()
            update: dict[str, object] = {"format_id": self.format_id}
            if represents_occupancy:
                fields = dict(base.fields)
                fields[_OCCUPANCY_PATH] = FieldCapability(
                    level=CapabilityLevel.FULL, notes="Stub target that represents occupancy."
                )
                update["fields"] = fields
            return base.model_copy(update=update)

    return StubExporter(format_id=format_id)


def _registry_with(exporter: ExporterPlugin) -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for builtin in builtin_exporters():
        reg.register_exporter(builtin)
    reg.register_exporter(exporter)
    return reg


def test_a_target_that_does_not_declare_the_field_warns() -> None:
    # The default: a format that says nothing about atoms.occupancies cannot represent it (the
    # capability defaults to NONE), so a partial site is dropped and the warning fires.
    reg = _registry_with(_stub_exporter("plain_stub"))
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, reg.capability_matrix(), "plain_stub")

    assert _OCCUPANCY_PATH in {e.path for e in diff.removed}
    assert _WARNING_CODE in [w.code for w in diff.warnings]


def test_declaring_the_field_writable_suppresses_the_warning() -> None:
    # The P6 escape hatch: a format that declares a writable atoms.occupancies capability
    # *represents* occupancy and silences this with no edit to the pre-flight diff. The real CIF
    # exporter uses exactly this mechanism.
    reg = _registry_with(_stub_exporter("occupancy_aware_stub", represents_occupancy=True))
    source = _occupancies("0.5", "1.0")
    diff = build_preflight(source, reg.capability_matrix(), "occupancy_aware_stub")
    assert _WARNING_CODE not in [w.code for w in diff.warnings]


# --------------------------------------------------------------------------------------------
# The warning in the Conversion Report
# --------------------------------------------------------------------------------------------


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
