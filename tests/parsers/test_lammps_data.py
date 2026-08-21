"""LAMMPS data (configuration/restart) parser tests (v1.3 M48-S1; Part 3 §3).

A data file states no unit style and no element symbols, and may state no atom style, so
every golden is the *recovered* object: the plain parse refuses (recoverably) and a
compound ``recovery_context`` (``ambiguous_units`` + ``missing_species`` [+
``ambiguous_atom_style``]) resolves it in one re-read. The golden cases under
``tests/golden/lammps_data/`` are diffed through the same external-truth machinery every
other format uses (Part 8 §3); the unit tests pin the refusal order, the edges-direct box
(no bounding-box inversion), the per-style column layouts, the shared image-flag carry, and
the topology vs. Masses reporting model.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_matches_golden
from xtalate.parsers.lammps_data import make_lammps_data_parser
from xtalate.sdk import ParseError, ParseResult

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_data"
PARSER = make_lammps_data_parser()

# Each golden's compound recovery_context (what the orchestrator threads together for the
# final resolving re-read) and its expected issue codes after that re-read.
_CASES: dict[str, tuple[dict[str, dict[str, object]], list[str]]] = {
    "atomic-metal-ortho": (
        {
            "ambiguous_units": {"choice": "metal", "parameters": {}},
            "missing_species": {"choice": "species_map", "parameters": {"species": "1:Ar 2:Ne"}},
        },
        ["LAMMPSDATA_UNITS_INTERPRETED", "LAMMPSDATA_SPECIES_SUPPLIED"],
    ),
    "charge-real-velocities": (
        {
            "ambiguous_units": {"choice": "real", "parameters": {}},
            "missing_species": {"choice": "species_map", "parameters": {"species": "1:O 2:H"}},
        },
        ["LAMMPSDATA_UNITS_INTERPRETED", "LAMMPSDATA_SPECIES_SUPPLIED"],
    ),
    "full-triclinic-topology": (
        {
            "ambiguous_units": {"choice": "metal", "parameters": {}},
            "missing_species": {"choice": "species_map", "parameters": {"species": "1:C 2:H"}},
        },
        [
            "LAMMPSDATA_IMAGE_FLAGS_CARRIED",
            "LAMMPSDATA_TOPOLOGY_CARRIED",
            "LAMMPSDATA_UNITS_INTERPRETED",
            "LAMMPSDATA_SPECIES_SUPPLIED",
        ],
    ),
    "full-no-style-comment": (
        {
            "ambiguous_atom_style": {"choice": "full", "parameters": {}},
            "ambiguous_units": {"choice": "metal", "parameters": {}},
            "missing_species": {"choice": "species_map", "parameters": {"species": "1:Na 2:Cl"}},
        },
        [
            "LAMMPSDATA_ATOM_STYLE_INTERPRETED",
            "LAMMPSDATA_UNITS_INTERPRETED",
            "LAMMPSDATA_SPECIES_SUPPLIED",
        ],
    ),
}


def _source(case: str) -> bytes:
    return (GOLDEN / case / "structure.data").read_bytes()


def _recover(case: str) -> ParseResult:
    """Drive ``parse_recover`` with the case's compound context, exactly as the generator does."""
    ctx, _ = _CASES[case]
    first = next(iter(ctx))
    hint = {
        "ambiguous_units": "ambiguous_units",
        "missing_species": "supply_species",
        "ambiguous_atom_style": "ambiguous_atom_style",
    }[first]
    entry = ctx[first]
    choice = entry["choice"]
    parameters = entry["parameters"]
    assert isinstance(choice, str)
    assert isinstance(parameters, dict)
    return PARSER.parse_recover(
        io.BytesIO(_source(case)),
        filename="structure.data",
        hint=hint,
        choice=choice,
        parameters=parameters,
        recovery_context=ctx,
    )


# --- golden fidelity -----------------------------------------------------------------


@pytest.mark.parametrize("case", sorted(_CASES))
def test_recovered_object_matches_golden(case: str) -> None:
    expected = (GOLDEN / case / "expected.canonical.json").read_text()
    assert_matches_golden(_recover(case).canonical, expected)


@pytest.mark.parametrize("case", sorted(_CASES))
def test_recovered_issue_codes_match(case: str) -> None:
    _, expected_codes = _CASES[case]
    assert [i.code for i in _recover(case).issues] == expected_codes


# --- refusal order: atom style → units → species -------------------------------------


def test_undeclared_units_refuse_with_ambiguous_units_hint() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(_source("atomic-metal-ortho")), filename="structure.data")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDATA_AMBIGUOUS_UNITS"
    assert issue.recovery_hint == "ambiguous_units"


def test_missing_species_refuses_once_units_are_supplied() -> None:
    """With units resolved but no species, the next refusal is missing_species (dependency)."""
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(_source("atomic-metal-ortho")),
            filename="structure.data",
            hint="ambiguous_units",
            choice="metal",
            parameters={},
        )
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDATA_MISSING_SPECIES"
    assert issue.recovery_hint == "supply_species"


def test_undeclared_atom_style_refuses_first_of_all() -> None:
    """A file whose Atoms section names no style cannot even read its columns, so the atom-style
    refusal precedes units — proven by the plain parse on the no-style golden."""
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(_source("full-no-style-comment")), filename="structure.data")
    issue = exc.value.issues[0]
    assert issue.code == "LAMMPSDATA_AMBIGUOUS_ATOM_STYLE"
    assert issue.recovery_hint == "ambiguous_atom_style"


def test_declared_style_is_never_overridden() -> None:
    """A file that declares its style (``Atoms # atomic``) is genuine source data: a recovery
    override that disagrees is a malformed request, not a silent re-interpretation."""
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(_source("atomic-metal-ortho")),
            filename="structure.data",
            hint="ambiguous_atom_style",
            choice="full",
            parameters={},
            recovery_context={
                "ambiguous_atom_style": {"choice": "full", "parameters": {}},
                "ambiguous_units": {"choice": "metal", "parameters": {}},
                "missing_species": {
                    "choice": "species_map",
                    "parameters": {"species": "1:Ar 2:Ne"},
                },
            },
        )
    assert exc.value.issues[0].code == "LAMMPSDATA_MALFORMED"
    assert "declares atom style" in exc.value.issues[0].message


# --- unsupported units / styles refuse (not offered as choices) ----------------------


def test_declared_unsupported_style_refuses() -> None:
    src = _source("atomic-metal-ortho").replace(b"Atoms # atomic", b"Atoms # sphere")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(src), filename="structure.data")
    assert exc.value.issues[0].code == "LAMMPSDATA_UNSUPPORTED_ATOM_STYLE"


def test_unknown_recovery_style_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(_source("atomic-metal-ortho")),
            filename="structure.data",
            hint="ambiguous_units",
            choice="lj",
            parameters={},
        )
    assert exc.value.issues[0].code == "LAMMPSDATA_UNSUPPORTED_UNITS"


def test_unknown_recovery_atom_style_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(_source("full-no-style-comment")),
            filename="structure.data",
            hint="ambiguous_atom_style",
            choice="sphere",
            parameters={},
        )
    assert exc.value.issues[0].code == "LAMMPSDATA_UNSUPPORTED_ATOM_STYLE"


# --- box: edges written direct, no bounding-box inversion ----------------------------


def test_triclinic_box_reads_edges_directly_without_inversion() -> None:
    """A data file's tilt params are the restricted *edge* vectors themselves — unlike a dump's
    axis-aligned bounding box, they are used as written, never inverted (they coincide only at
    zero tilt)."""
    frame = _recover("full-triclinic-topology").canonical.frames[0]
    assert frame.cell is not None
    # xlo/xhi=0/10, ylo/yhi=0/9, zlo/zhi=0/8, xy/xz/yz=1.5/0.5/0.25 -> lower-triangular lattice.
    assert frame.cell.lattice_vectors.tolist() == [
        [10.0, 0.0, 0.0],
        [1.5, 9.0, 0.0],
        [0.5, 0.25, 8.0],
    ]


def test_atoms_sorted_by_ascending_id() -> None:
    """The atomic golden lists ids out of order (3,1,4,2); the per-atom arrays come back id-sorted
    so id/type/position/carry all line up."""
    obj = _recover("atomic-metal-ortho").canonical
    ids = np.asarray(obj.user_metadata.custom_per_atom["lammps_data:id"]).tolist()
    assert ids == [1.0, 2.0, 3.0, 4.0]
    # id 1 sits at (1,1,1); id 4 at (9,3,2) — positions follow the sorted ids, not file order.
    assert obj.frames[0].atoms.positions[0].tolist() == [1.0, 1.0, 1.0]
    assert obj.frames[0].atoms.positions[3].tolist() == [9.0, 3.0, 2.0]


# --- per-style columns: charge, molecule-id, image flags -----------------------------


def test_charge_style_charges_land_in_electronic() -> None:
    obj = _recover("charge-real-velocities").canonical
    assert obj.frames[0].electronic.charges is not None
    assert obj.frames[0].electronic.charges.tolist() == [-0.8, 0.4, 0.4]


def test_atomic_style_has_no_charges() -> None:
    """The atomic layout has no q column, so charges stay absent (P3), not zero-filled."""
    assert _recover("atomic-metal-ortho").canonical.frames[0].electronic.charges is None


def test_full_style_carries_molecule_id() -> None:
    obj = _recover("full-triclinic-topology").canonical
    mol = np.asarray(obj.user_metadata.custom_per_atom["lammps_data:molecule_id"])
    assert mol.tolist() == [1.0] * 8


def test_image_flags_carried_under_the_shared_key_and_never_applied() -> None:
    """A complete ix/iy/iz triple is carried under the *shared* IMAGE_FLAGS_CARRY_KEY (identical
    physical meaning to a dump's) and never applied on parse (D43); positions stay as written."""
    result = _recover("full-triclinic-topology")
    codes = [i.code for i in result.issues]
    assert "LAMMPSDATA_IMAGE_FLAGS_CARRIED" in codes
    flags = np.asarray(result.canonical.user_metadata.custom_per_atom["lammps_dump:image_flags"])
    assert flags[3].tolist() == [-1.0, 0.0, 0.0]  # atom id 4 carries ix=-1
    # Positions are the coordinates as written, unit-converted — never shifted by the flags.
    assert result.canonical.frames[0].atoms.positions[3].tolist() == [0.6, 0.1, 1.7]


def test_partial_image_flag_triple_is_malformed() -> None:
    """Image flags are all-or-none per file; a row with only some of ix/iy/iz is malformed."""
    src = _source("full-triclinic-topology").replace(
        b"4 1 2 0.06 0.6 0.1 1.7 -1 0 0", b"4 1 2 0.06 0.6 0.1 1.7 -1 0"
    )
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src),
            filename="structure.data",
            hint="ambiguous_units",
            choice="metal",
            parameters={},
            recovery_context=_CASES["full-triclinic-topology"][0],
        )
    assert exc.value.issues[0].code == "LAMMPSDATA_MALFORMED"


# --- units: velocities and masses converted from the chosen style --------------------


def test_metal_velocities_converted_angstrom_per_picosecond() -> None:
    obj = _recover("full-triclinic-topology").canonical
    velocities = obj.frames[0].dynamics.velocities
    assert velocities is not None
    # 0.001 Å/ps -> 1e-6 Å/fs (metal velocity factor ×1e-3).
    assert velocities[1].tolist() == [1e-6, 0.0, 0.0]


def test_masses_land_in_atoms_masses_amu() -> None:
    obj = _recover("atomic-metal-ortho").canonical
    masses = obj.frames[0].atoms.masses
    assert masses is not None
    # metal masses are already amu (×1); id-sorted types are 1,2,1,2 -> Ar Ne Ar Ne.
    assert masses.tolist() == [39.948, 20.18, 39.948, 20.18]


def test_absent_velocities_stay_none() -> None:
    assert _recover("atomic-metal-ortho").canonical.frames[0].dynamics.velocities is None


# --- topology vs. Masses reporting model ---------------------------------------------


def test_mass_only_file_reports_no_topology_loss() -> None:
    """A file with a Masses table but no topology sections must NOT report topology loss: masses
    live in atoms.masses (the exporter regenerates the section), so nothing is carried."""
    codes = [i.code for i in _recover("atomic-metal-ortho").issues]
    assert "LAMMPSDATA_TOPOLOGY_CARRIED" not in codes
    assert "LAMMPSDATA_UNMAPPED_SECTION_CARRIED" not in codes


def test_standard_topology_carried_without_unmapped_warning() -> None:
    """Bonds + Bond Coeffs are recognized sections: they ride under the summary TOPOLOGY_CARRIED,
    never the UNMAPPED_SECTION_CARRIED reserved for unrecognized keywords."""
    result = _recover("full-triclinic-topology")
    codes = [i.code for i in result.issues]
    assert "LAMMPSDATA_TOPOLOGY_CARRIED" in codes
    assert "LAMMPSDATA_UNMAPPED_SECTION_CARRIED" not in codes
    topo = result.canonical.user_metadata.custom_global["lammps_data:topology"]
    assert isinstance(topo, dict)
    sections = topo["sections"]
    assert isinstance(sections, list)
    names = [s["section"] for s in sections if isinstance(s, dict)]
    assert names == ["Bonds", "Bond Coeffs"]
    assert topo["header_counts"] == ["7 bonds", "1 bond types"]


def test_unrecognized_section_warns_unmapped() -> None:
    """An unknown keyword (not a topology section, not a ``* Coeffs``) additionally warns
    UNMAPPED_SECTION_CARRIED — the loss is named, never silent."""
    src = _source("full-triclinic-topology").replace(
        b"Bond Coeffs\n\n1 300.0 1.09\n", b"Bond Coeffs\n\n1 300.0 1.09\n\nMystery\n\n1 42\n"
    )
    result = PARSER.parse_recover(
        io.BytesIO(src),
        filename="structure.data",
        hint="ambiguous_units",
        choice="metal",
        parameters={},
        recovery_context=_CASES["full-triclinic-topology"][0],
    )
    unmapped = [i for i in result.issues if i.code == "LAMMPSDATA_UNMAPPED_SECTION_CARRIED"]
    assert len(unmapped) == 1
    assert "'Mystery'" in unmapped[0].message


# --- malformed / empty ---------------------------------------------------------------


def test_empty_file_refuses() -> None:
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(b""), filename="structure.data")
    assert exc.value.issues[0].code == "LAMMPSDATA_EMPTY"


def test_missing_box_bound_is_malformed() -> None:
    src = _source("atomic-metal-ortho").replace(b"0.0 12.0 zlo zhi\n", b"")
    with pytest.raises(ParseError) as exc:
        PARSER.parse(io.BytesIO(src), filename="structure.data")
    assert exc.value.issues[0].code == "LAMMPSDATA_MALFORMED"
    assert "zlo" in exc.value.issues[0].message


def test_velocity_id_mismatch_is_malformed() -> None:
    """Velocities must name exactly the atom ids — a mismatch is refused, never trimmed/padded."""
    src = _source("charge-real-velocities").replace(b"3 0.0 -0.001 0.002", b"9 0.0 -0.001 0.002")
    with pytest.raises(ParseError) as exc:
        PARSER.parse_recover(
            io.BytesIO(src),
            filename="structure.data",
            hint="ambiguous_units",
            choice="real",
            parameters={},
            recovery_context=_CASES["charge-real-velocities"][0],
        )
    assert exc.value.issues[0].code == "LAMMPSDATA_MALFORMED"
    assert "atom ids do not match" in exc.value.issues[0].message


# --- sniff / capabilities / streaming ------------------------------------------------


def test_sniff_identifies_data_by_box_header() -> None:
    assert PARSER.sniff(b"title\n\n4 atoms\n\n0.0 10.0 xlo xhi\n", "s.data") == 0.95
    assert PARSER.sniff(b"ITEM: TIMESTEP\n0\n", "x.dump") == 0.0


def test_does_not_stream() -> None:
    assert PARSER.supports_streaming() is False


def test_capabilities_declare_read_side_only() -> None:
    caps = PARSER.capabilities()
    assert caps.format_id == "lammps_data"
    assert caps.direction == "read"
    assert caps.max_frames == 1  # a single configuration
    assert caps.holds_image_flags is True
    assert caps.required_fields == []
    assert caps.fields["atoms.positions"].level.value == "full"
