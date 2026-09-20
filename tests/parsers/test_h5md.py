"""H5MD parser field-mapping, error-code, and torn-tail recovery tests (v2.0 M74 S2).

Each fixture is built in memory with ``h5py`` (a ``BytesIO`` H5MD file) and re-parsed through the
public ``H5MDParser``, asserting the §4 canonical mapping: velocity/force/mass/charge/energy land on
their canonical fields in canonical units, per-frame observables ride
``user_metadata.custom_per_frame['h5md:<name>']``, the box maps to ``cell``, and every *absent*
optional group launders to ``None`` — never zeros or a fabricated default (P3).
"""

from __future__ import annotations

from io import BytesIO

import h5py
import numpy as np
import pytest

from xtalate.parsers.h5md import H5MDParser
from xtalate.sdk import ParseError, ParseResult


def _time_dep(group: h5py.Group, name: str, values: list[np.ndarray], *, unit: str | None) -> None:
    """Write a time-dependent element ``name/{step,time,value}`` with a per-step VLEN ``value``."""
    sub = group.create_group(name)
    vlen = h5py.vlen_dtype(values[0].dtype)
    value = sub.create_dataset("value", shape=(len(values),), dtype=vlen)
    for i, row in enumerate(values):
        value[i] = np.asarray(row).reshape(-1)
    if unit is not None:
        value.attrs["unit"] = unit
    sub.create_dataset("step", data=np.arange(len(values), dtype=np.int64))
    sub.create_dataset("time", data=np.arange(len(values), dtype=np.float64))


def _minimal_h5md(
    *,
    positions: list[np.ndarray],
    species: list[np.ndarray],
    velocities: list[np.ndarray] | None = None,
    forces: list[np.ndarray] | None = None,
    masses: np.ndarray | None = None,
    charges: np.ndarray | None = None,
    observables: dict[str, np.ndarray] | None = None,
    box_edges: np.ndarray | None = None,
    boundary: list[bytes] | None = None,
    creator: tuple[str, str] | None = ("test-writer", "9.9"),
    position_unit: str | None = None,
) -> BytesIO:
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        h5md = f.create_group("h5md")
        h5md.attrs["version"] = np.asarray([1, 1], dtype=np.int64)
        if creator is not None:
            grp = h5md.create_group("creator")
            grp.attrs["name"] = creator[0]
            grp.attrs["version"] = creator[1]
        particles = f.create_group("particles/all")
        _time_dep(particles, "position", positions, unit=position_unit)
        _time_dep(particles, "species", species, unit=None)
        if velocities is not None:
            _time_dep(particles, "velocity", velocities, unit="Angstrom/fs")
        if forces is not None:
            _time_dep(particles, "force", forces, unit="eV/Angstrom")
        if masses is not None:
            ds = particles.create_dataset("mass", data=np.asarray(masses, dtype=np.float64))
            ds.attrs["unit"] = "u"
        if charges is not None:
            ds = particles.create_dataset("charge", data=np.asarray(charges, dtype=np.float64))
            ds.attrs["unit"] = "e"
        if box_edges is not None:
            box = particles.create_group("box")
            box.attrs["dimension"] = np.int64(3)
            box.create_dataset("edges", data=np.asarray(box_edges, dtype=np.float64))
            if boundary is not None:
                box.create_dataset("boundary", data=np.asarray(boundary))
        if observables is not None:
            obs = f.create_group("observables")
            for name, series in observables.items():
                sub = obs.create_group(name)
                sub.create_dataset("value", data=np.asarray(series, dtype=np.float64))
                sub.create_dataset("step", data=np.arange(len(series), dtype=np.int64))
                sub.create_dataset("time", data=np.arange(len(series), dtype=np.float64))
    buf.seek(0)
    return buf


def _parse(buf: BytesIO) -> ParseResult:
    return H5MDParser().parse(buf, filename="fixture.h5md")


def test_positions_and_species_map_to_atoms() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0], [0, 0, 1.0]])],
        species=[np.array([1, 8], dtype=np.int64)],
    )
    obj = _parse(buf).canonical
    assert obj.frames[0].atoms.symbols == ["H", "O"]
    np.testing.assert_allclose(obj.frames[0].atoms.positions, [[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def test_velocity_maps_to_dynamics_velocities() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]])],
        species=[np.array([1], dtype=np.int64)],
        velocities=[np.array([[0.5, 0.0, -0.5]])],
    )
    obj = _parse(buf).canonical
    velocities = obj.frames[0].dynamics.velocities
    assert velocities is not None
    np.testing.assert_allclose(velocities, [[0.5, 0.0, -0.5]])


def test_force_maps_to_dynamics_forces() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]])],
        species=[np.array([1], dtype=np.int64)],
        forces=[np.array([[0.1, -0.2, 0.3]])],
    )
    obj = _parse(buf).canonical
    forces = obj.frames[0].dynamics.forces
    assert forces is not None
    np.testing.assert_allclose(forces, [[0.1, -0.2, 0.3]])


def test_mass_maps_to_atoms_masses() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0], [0, 0, 1.0]])],
        species=[np.array([1, 8], dtype=np.int64)],
        masses=np.array([1.008, 15.999]),
    )
    obj = _parse(buf).canonical
    masses = obj.frames[0].atoms.masses
    assert masses is not None
    np.testing.assert_allclose(masses, [1.008, 15.999])


def test_charge_maps_to_electronic_charges() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0], [0, 0, 1.0]])],
        species=[np.array([1, 8], dtype=np.int64)],
        charges=np.array([0.4, -0.8]),
    )
    obj = _parse(buf).canonical
    charges = obj.frames[0].electronic.charges
    assert charges is not None
    np.testing.assert_allclose(charges, [0.4, -0.8])


def test_potential_energy_observable_maps_to_total_energy() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]]), np.array([[0.1, 0, 0]])],
        species=[np.array([1], dtype=np.int64), np.array([1], dtype=np.int64)],
        observables={"potential_energy": np.array([-12.5, -12.6])},
    )
    obj = _parse(buf).canonical
    assert obj.frames[0].electronic.total_energy == pytest.approx(-12.5)
    assert obj.frames[1].electronic.total_energy == pytest.approx(-12.6)


def test_other_observable_rides_custom_per_frame() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]]), np.array([[0.1, 0, 0]])],
        species=[np.array([1], dtype=np.int64), np.array([1], dtype=np.int64)],
        observables={"temperature": np.array([300.0, 305.0])},
    )
    obj = _parse(buf).canonical
    # A numeric per-frame series coerces to a length-F array (the canonical left-to-right union).
    series = np.asarray(obj.user_metadata.custom_per_frame["h5md:temperature"])
    np.testing.assert_allclose(series, [300.0, 305.0])


def test_box_maps_to_cell_and_pbc() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]])],
        species=[np.array([1], dtype=np.int64)],
        box_edges=np.diag([10.0, 11.0, 12.0]),
        boundary=[b"periodic", b"periodic", b"none"],
    )
    obj = _parse(buf).canonical
    cell = obj.frames[0].cell
    assert cell is not None
    np.testing.assert_allclose(cell.lattice_vectors, np.diag([10.0, 11.0, 12.0]))
    assert cell.pbc == (True, True, False)


def test_absent_optional_groups_launder_to_none() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]])],
        species=[np.array([1], dtype=np.int64)],
    )
    frame = _parse(buf).canonical.frames[0]
    assert frame.dynamics.velocities is None
    assert frame.dynamics.forces is None
    assert frame.atoms.masses is None
    assert frame.electronic.charges is None
    assert frame.electronic.total_energy is None
    assert frame.cell is None


def test_creator_is_recorded_in_provenance() -> None:
    buf = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0]])],
        species=[np.array([1], dtype=np.int64)],
        creator=("gromacs-h5md", "2024.1"),
    )
    prov = _parse(buf).canonical.provenance
    assert any("gromacs-h5md" in note and "2024.1" in note for note in prov.parse_notes)


def test_missing_position_group_is_refused() -> None:
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        f.create_group("h5md")
        particles = f.create_group("particles/all")
        _time_dep(particles, "species", [np.array([1], dtype=np.int64)], unit=None)
    buf.seek(0)
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(buf, filename="noposition.h5md")
    assert exc.value.issues[0].code == "H5MD_MISSING_REQUIRED_GROUP"


def test_non_h5md_hdf5_is_refused_as_malformed() -> None:
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        f.create_dataset("some_data", data=np.arange(10))
    buf.seek(0)
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(buf, filename="plain.hdf5")
    assert exc.value.issues[0].code == "H5MD_MISSING_REQUIRED_GROUP"


def test_multiple_particle_groups_are_refused() -> None:
    buf = BytesIO()
    with h5py.File(buf, "w") as f:
        f.create_group("h5md")
        for grp_name in ("all", "solvent"):
            grp = f.create_group(f"particles/{grp_name}")
            _time_dep(grp, "position", [np.array([[0.0, 0, 0]])], unit=None)
            _time_dep(grp, "species", [np.array([1], dtype=np.int64)], unit=None)
    buf.seek(0)
    with pytest.raises(ParseError) as exc:
        H5MDParser().parse(buf, filename="multi.h5md")
    issue = exc.value.issues[0]
    assert issue.code == "H5MD_MULTIPLE_PARTICLE_GROUPS"
    assert "all" in issue.message and "solvent" in issue.message
