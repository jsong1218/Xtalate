"""QE pw.x input exporter — the write side of M51 (v1.4 M51-S1, D192/D193).

These tests pin the exporter as the exact inverse of the M50 parser and prove the invariants the
slice guarantees:

* **Structural write, ``ibrav = 0`` always.** Any lattice — including a highly symmetric cubic
  cell — is written as an explicit ``CELL_PARAMETERS {angstrom}`` block with ``ibrav = 0``, never
  a reverse-derived ``ibrav`` code (D43). ``nat``/``ntyp`` are correct.
* **No invented physics (P1/P4).** ``ecutwfc``, k-points, and pseudopotential filenames are written
  only from carried QE-originated data; a non-QE object exports with **no** cutoff and **no**
  ``K_POINTS`` card, a placeholder (non-real) pseudopotential token, and a ``QEIN_INCOMPLETE_INPUT``
  warning naming every run-required entry the user must supply.
* **Carry-back only what the object holds.** A QE-originated object's pseudopotentials, ``K_POINTS``
  card, namelist entries, and recognized simulation context come back verbatim — so a complete QE
  input re-exports with **no** ``QEIN_INCOMPLETE_INPUT``.
* **Masses resolve through the existing ``missing_masses`` scenario.** ``atoms.masses`` is a write
  ``required_field``; the pre-flight refuses an object without them and ``standard_masses`` fills
  IUPAC standard weights (never a QE-specific recovery).
* **A trajectory is a recovery, not a refusal.** ``max_frames=1`` + ``frame_selection`` — a
  multi-frame object routes through the existing scenario, never an outright refusal; a lattice-less
  object routes through ``missing_lattice``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from tests._format_helpers import assert_scientifically_equal
from xtalate.conversion import ConversionEngine
from xtalate.exporters.qe_pw_in import make_qe_pw_in_exporter
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject, load_canonical
from xtalate.sdk.qe import (
    _ATOMIC_SPECIES_KEY,
    _NAMELISTS_KEY,
    _PSEUDOPOTENTIALS_KEY,
    _UNMAPPED_CARDS_KEY,
)

GOLDEN = Path(__file__).parent.parent / "golden" / "qe_pw_in"
_POSCAR_GOLDEN = Path(__file__).parent.parent / "golden" / "poscar" / "nacl-primitive"
_XYZ_GOLDEN = Path(__file__).parent.parent / "golden" / "xyz" / "water-traj"

_INCOMPLETE = "QEIN_INCOMPLETE_INPUT"
_PLACEHOLDER = "__PSEUDOPOTENTIAL_NOT_PROVIDED__.UPF"


def _load(case: str) -> CanonicalObject:
    return load_canonical((GOLDEN / case / "expected.canonical.json").read_text())


def _export(obj: CanonicalObject) -> bytes:
    buf = io.BytesIO()
    make_qe_pw_in_exporter().export(obj, buf)
    return buf.getvalue()


def _reparse(written: bytes) -> CanonicalObject:
    return make_qe_pw_in_parser().parse(io.BytesIO(written), filename=None).canonical


def _strip_qe_carries(obj: CanonicalObject) -> CanonicalObject:
    """A copy of a QE-originated object with the QE carries and simulation context removed — the
    non-QE-originated shape the honest-incompleteness tests need."""
    um = obj.user_metadata.model_copy(update={"custom_global": {}})
    return obj.model_copy(update={"user_metadata": um, "simulation": None})


def _convert(
    obj: CanonicalObject,
    recovery_choices: dict[str, dict[str, Any]] | None = None,
    *,
    source_format_id: str = "qe_pw_in",
) -> Any:
    return ConversionEngine(default_registry()).convert(
        obj,
        source_format_id=source_format_id,
        target_format_id="qe_pw_in",
        recovery_choices=recovery_choices,
    )


# --- structural write --------------------------------------------------------------------------


def test_export_writes_a_parseable_ibrav_zero_input() -> None:
    """A canonical with a full lattice + symbols + masses writes a parseable pw.x input that
    re-parses to a scientifically equal object — the structural identity at the exporter level."""
    obj = _load("explicit-angstrom")
    written = _export(obj).decode("utf-8")
    assert "ibrav = 0" in written
    assert "CELL_PARAMETERS {angstrom}" in written
    assert "ATOMIC_POSITIONS {angstrom}" in written
    assert "ATOMIC_SPECIES" in written
    assert "nat = 1" in written
    assert "ntyp = 1" in written
    assert_scientifically_equal(obj, _reparse(written.encode("utf-8")))


def test_ibrav_zero_always_even_for_a_cubic_cell() -> None:
    """The D43 guard: a highly symmetric cubic cell is written with explicit vectors and
    ``ibrav = 0``, never a derived ``ibrav = 1``."""
    obj = _load("ibrav1-sc")  # the canonical holds the 4.0 Å cubic lattice from ibrav = 1
    written = _export(obj).decode("utf-8")
    assert "ibrav = 0" in written
    assert "ibrav = 1" not in written
    assert "ibrav = 2" not in written
    assert "ibrav = 3" not in written
    # The explicit vectors are the same cubic cell, in angstrom.
    assert "   4.0 0.0 0.0" in written
    assert "   0.0 4.0 0.0" in written
    assert "   0.0 0.0 4.0" in written
    assert_scientifically_equal(obj, _reparse(_export(obj)))


def test_carried_payloads_write_back_verbatim() -> None:
    """A QE-originated object's pseudopotentials, K_POINTS card, carried namelist entry, and
    recognized simulation context come back — the carry-back that makes the identity round-trip
    complete and warning-free."""
    obj = _load("carry-kpoints")
    written = _export(obj).decode("utf-8")
    # the carried unit is written back (the brace spelling is one interchangeable QE form)
    assert "K_POINTS automatic" in written
    assert "4 4 4 0 0 0" in written
    assert "fe.pbe.UPF" in written and "o.pbe.UPF" in written
    # ecutwfc/ecutrho are &SYSTEM variables in QE (review R3 QE-B) — the exporter writes the
    # recognized simulation context into the namelist the mapping names, i.e. back into
    # &SYSTEM, restoring the round-trip to the real placement.
    assert "ecutwfc = '40.0'" in written
    sys_block = written.split("&SYSTEM")[1].split("/")[0]
    assert "ecutwfc" in sys_block and "ecutrho" in sys_block
    assert "conv_thr = '1e-08'" in written  # &electrons
    assert "smearing = 'gaussian'" in written  # &system
    assert "nspin = 2" in written  # the carried &system entry
    # The re-parse reproduces the object scientifically (the full S2 identity lives in the
    # round-trip suite; this pins the writer's carry-back end to end).
    assert_scientifically_equal(obj, _reparse(_export(obj)))
    # A complete QE input is not incomplete: no QEIN_INCOMPLETE_INPUT.
    exporter = make_qe_pw_in_exporter()
    assert exporter.export_warnings(obj) == []


# --- honest incompleteness ---------------------------------------------------------------------


def test_non_qe_object_exports_with_placeholder_and_incompleteness_warning() -> None:
    """A non-QE-originated object (no pseudopotentials, no K_POINTS, no carried ecutwfc) exports
    with a placeholder pseudopotential token and one QEIN_INCOMPLETE_INPUT warning naming
    ecutwfc, k-points, and the per-species pseudopotentials."""
    obj = _strip_qe_carries(_load("explicit-angstrom"))
    written = _export(obj).decode("utf-8")
    assert _PLACEHOLDER in written
    # The placeholder cannot be mistaken for a real filename.
    assert _PLACEHOLDER.startswith("__") and "NOT_PROVIDED" in _PLACEHOLDER
    warnings = make_qe_pw_in_exporter().export_warnings(obj)
    assert len(warnings) == 1
    assert warnings[0].code == _INCOMPLETE
    message = warnings[0].message
    assert "ecutwfc" in message
    assert "K_POINTS" in message
    assert "Fe" in message  # the per-species pseudopotential
    assert "structurally complete but not yet runnable" in message


def test_no_invented_physics() -> None:
    """The written file contains no ecutwfc value and no K_POINTS card when the source carried
    none — never a defaulted cutoff or mesh."""
    obj = _strip_qe_carries(_load("explicit-angstrom"))
    written = _export(obj).decode("utf-8")
    assert "ecutwfc" not in written
    assert "K_POINTS" not in written
    # ... and the placeholder is the only pseudopotential token (never a plausible filename).
    assert _PLACEHOLDER in written


def test_incomplete_warning_names_only_what_is_missing() -> None:
    """Only the actually-missing entries are named: a QE object with pseudos + K_POINTS but no
    ecutwfc warns about the cutoff alone."""
    obj = _load("carry-kpoints")
    # Remove the simulation context (ecutwfc etc.) but keep the pseudos and K_POINTS carries.
    header_obj = obj
    sim = header_obj.simulation
    assert sim is not None
    stripped = header_obj.model_copy(update={"simulation": None})
    warnings = make_qe_pw_in_exporter().export_warnings(stripped)
    assert len(warnings) == 1
    assert warnings[0].code == _INCOMPLETE
    assert "ecutwfc" in warnings[0].message
    assert "K_POINTS" not in warnings[0].message
    assert "Fe" not in warnings[0].message  # pseudos are still carried


# --- recovery scenarios (existing, reused unchanged) -------------------------------------------


def test_masses_route_through_missing_masses() -> None:
    """atoms.masses is a write required_field: the pre-flight refuses an object without them via
    the existing missing_masses scenario, and standard_masses completes the export — never a
    QE-specific mass recovery."""
    obj = load_canonical((_POSCAR_GOLDEN / "expected.canonical.json").read_text())
    result = _convert(obj, source_format_id="poscar")
    assert result.report.status == "refused"
    scenarios = [s["scenario"] for s in result.report.refusal["unresolved_scenarios"]]
    assert "missing_masses" in scenarios

    result = _convert(
        obj,
        {"missing_masses": {"choice": "standard_masses", "parameters": {}}},
        source_format_id="poscar",
    )
    assert result.report.status == "completed"
    assert result.output is not None
    written = result.output.decode("utf-8")
    assert "ATOMIC_SPECIES" in written
    assert _PLACEHOLDER in written  # standard masses filled; pseudos honestly absent
    reparse = _reparse(result.output)
    assert reparse.frames[0].atoms.masses is not None


def test_missing_lattice_routes_through_missing_lattice() -> None:
    """A lattice-less object routes through the existing missing_lattice recovery — the cell is
    never fabricated by the exporter itself."""
    obj = load_canonical((_XYZ_GOLDEN / "expected.canonical.json").read_text())
    single = obj.single_frame(0)  # isolate one frame so only the lattice gap is exercised
    result = _convert(single, source_format_id="xyz")
    assert result.report.status == "refused"
    scenarios = [s["scenario"] for s in result.report.refusal["unresolved_scenarios"]]
    assert "missing_lattice" in scenarios


def test_multi_frame_routes_through_frame_selection() -> None:
    """max_frames = 1: a multi-frame object routes through the existing frame_selection scenario
    (one frame chosen, the rest recorded as an Assumption) — not an outright refusal."""
    obj = load_canonical((_XYZ_GOLDEN / "expected.canonical.json").read_text())
    assert len(obj.frames) == 2
    result = _convert(obj, source_format_id="xyz")
    assert result.report.status == "refused"
    scenarios = [s["scenario"] for s in result.report.refusal["unresolved_scenarios"]]
    assert "frame_selection" in scenarios

    result = _convert(
        obj,
        {
            "frame_selection": {"choice": "first", "parameters": {}},
            "missing_masses": {"choice": "standard_masses", "parameters": {}},
            "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
        },
        source_format_id="xyz",
    )
    assert result.report.status == "completed"
    assert result.output is not None
    assert "nat = 3" in result.output.decode("utf-8")


# --- value-level refusals (unrepresentable, D179) ---------------------------------------------


def test_one_element_with_two_masses_is_unrepresentable() -> None:
    """A pw.x ``ATOMIC_SPECIES`` table is one row per species label with a single mass, so one
    element carrying two masses (an isotope distinction) cannot be written without silently
    flattening it — the value-level gate refuses rather than collapses (P1)."""
    obj = _load("carry-kpoints")  # two atoms: Fe, O
    frame = obj.frames[0]
    # Make both atoms Fe with different masses — a clash the per-label table cannot express.
    atoms = frame.atoms.model_copy(update={"symbols": ["Fe", "Fe"], "masses": [55.845, 57.0]})
    clashed = obj.model_copy(update={"frames": [frame.model_copy(update={"atoms": atoms})]})
    reason = make_qe_pw_in_exporter().unrepresentable(clashed)
    assert reason is not None
    assert "more than one mass" in reason
    assert "'Fe'" in reason


def test_two_labels_resolving_to_one_element_is_unrepresentable() -> None:
    """The parser resolves every ``ATOMIC_SPECIES`` label to an element for ``atoms.symbols``, so
    two labels that resolve to one element (``Fe`` and ``Fe1``) cannot be told apart on the way
    back out — refused rather than silently merged (P1)."""
    obj = _load("carry-kpoints")
    existing = obj.user_metadata.custom_global[_ATOMIC_SPECIES_KEY]
    assert isinstance(existing, dict)
    # Add a second Fe label (e.g. an antiferromagnetic starting-magnetization split) the parser
    # collapses into the single symbol "Fe".
    table: dict[str, Any] = {**existing, "Fe1": [55.845, "fe.pbe.UPF"]}
    cg: dict[str, Any] = {**obj.user_metadata.custom_global, _ATOMIC_SPECIES_KEY: table}
    um = obj.user_metadata.model_copy(update={"custom_global": cg})
    reason = make_qe_pw_in_exporter().unrepresentable(obj.model_copy(update={"user_metadata": um}))
    assert reason is not None
    assert "resolve to element 'Fe'" in reason


def test_representable_qe_object_returns_none() -> None:
    """The clean golden — one label per element, one mass per element — is representable: the
    value-level gate passes it through so a normal conversion is never spuriously refused."""
    assert make_qe_pw_in_exporter().unrepresentable(_load("carry-kpoints")) is None


# --- capabilities ------------------------------------------------------------------------------


def test_capabilities_declare_the_write_side() -> None:
    caps = make_qe_pw_in_exporter().capabilities()
    assert caps.direction == "write"
    assert caps.format_id == "qe_pw_in"
    assert caps.max_frames == 1
    assert "atoms.symbols" in caps.required_fields
    assert "atoms.positions" in caps.required_fields
    assert "cell.lattice_vectors" in caps.required_fields
    assert "atoms.masses" in caps.required_fields
    writable = caps.writable_custom_keys["user_metadata.custom_global"]
    assert writable == [
        "qe:pseudopotentials",
        "qe_pw_in:namelists",
        "qe_pw_in:unmapped_cards",
        "qe_pw_in:atomic_species",
    ]
    # The QE carry keys are the identical strings the parser wrote (never forked).
    assert set(writable) == {
        _PSEUDOPOTENTIALS_KEY,
        _NAMELISTS_KEY,
        _UNMAPPED_CARDS_KEY,
        _ATOMIC_SPECIES_KEY,
    }
    # A structural pw.x input carries no dynamics/electronic labels.
    assert caps.fields["dynamics.velocities"].level == "none"
    assert caps.fields["electronic.total_energy"].level == "none"


def test_registration_flips_the_capability_matrix() -> None:
    """Registering the exporter makes qe_pw_in a read+write format and a valid --to target —
    the M50 staging state is closed (the /v1/capabilities HTTP surface mirrors this registry
    matrix with zero backend edits)."""
    registry = default_registry()
    matrix = registry.capability_matrix()
    assert matrix.field_capability("qe_pw_in", "write", "atoms.positions").level == "full"
    assert matrix.field_capability("qe_pw_in", "read", "atoms.positions").level == "full"
    assert "qe_pw_in" in {e.format_id for e in registry.exporters()}
