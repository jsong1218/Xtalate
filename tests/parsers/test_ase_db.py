"""ASE database (``.db``) parser tests — the M55 default-laundering suite (HARD GATE).

Mirror of ``tests/parsers/test_ase_traj.py``: ASE always hands back a fully-populated object,
so the parser's job is to turn the library's invented defaults — a zero cell, zeroed momenta,
atomic-number-derived masses, generated ``id``/``ctime``/``mtime``/``user``, an empty key-value
dict — back into ``None``/absence. The ``.db``-specific obligations are pinned here too: the
**multi-row refusal** (``ASEDB_MULTIPLE_ROWS``, recoverable per row via the
``asedb_row_selection`` scenario) and the **key-value carry** (per-row pairs + the ``data``
blob → ``user_metadata.custom_global['ase_db:<key>']`` with ``ASEDB_KV_CARRIED`` warnings —
carried, never interpreted).

The final tests are the **ASE-version canary** (D59): the installed ASE satisfies the
``pyproject.toml`` pin and the wrapped version appears in ``provenance.history[0].parser_version``.
"""

from __future__ import annotations

import io
import tempfile
import tomllib
from pathlib import Path

import ase
import numpy as np
import pytest
from ase import Atoms
from ase import units as ase_units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms
from ase.db import connect
from packaging.requirements import Requirement
from packaging.version import Version

from tests._format_helpers import parse_bytes
from xtalate.parsers.ase_db import AseDbParser, make_ase_db_parser
from xtalate.schema import CanonicalObject, Frame
from xtalate.sdk import ParseError

Row = tuple[Atoms, dict[str, object], dict[str, object]]


def _parser() -> AseDbParser:
    return make_ase_db_parser()


def _db_bytes(*rows: tuple[Atoms, dict[str, object], dict[str, object]]) -> bytes:
    """Serialise one or more ``(Atoms, key_value_pairs, data)`` rows to in-memory ``.db``
    bytes via ``ase.db`` (SQLite), mirroring how ``test_ase_traj`` builds tiny in-line ULM
    fixtures."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = connect(tmp.name, use_lock_file=False)
        for atoms, kv, data in rows:
            db.write(atoms, key_value_pairs=kv, data=data)
        tmp.flush()
        return Path(tmp.name).read_bytes()


def _row(*rows: Row, filename: str = "sample.db") -> tuple[Frame, CanonicalObject]:
    obj = parse_bytes(_parser(), _db_bytes(*rows), filename=filename).canonical
    return obj.frames[0], obj


def _bare() -> Atoms:
    return Atoms("H", positions=[[0.0, 0.0, 0.0]])


# --- default-laundering suite (the point of an ASE-backed parser) ---------------------


def test_launder_absent_cell_to_none() -> None:
    # No cell written: ASE fabricates an all-zero 3x3; the canonical object must record None.
    frame, _ = _row((_bare(), {}, {}))
    assert frame.cell is None


def test_launder_absent_momenta_to_none() -> None:
    frame, _ = _row((_bare(), {}, {}))
    assert frame.dynamics.velocities is None


def test_launder_absent_masses_to_none() -> None:
    frame, _ = _row((_bare(), {}, {}))
    assert frame.atoms.masses is None


def test_launder_absent_charges_and_magmoms_to_none() -> None:
    frame, _ = _row((_bare(), {}, {}))
    assert frame.electronic.charges is None
    assert frame.electronic.magnetic_moments is None


def test_launder_ase_generated_row_metadata_to_absence() -> None:
    # ASE generates id/ctime/mtime/user (and a unique_id) for every row; none of that is source
    # data, so none of it may appear in the canonical object — and an empty key-value dict is
    # the same manufactured default, so there is nothing under custom_global either.
    obj = parse_bytes(_parser(), _db_bytes((_bare(), {}, {})), filename="sample.db").canonical
    assert obj.user_metadata.custom_global == {}
    assert obj.user_metadata.custom_per_frame == {}


# --- field mapping (present-and-correct) ----------------------------------------------


def test_masses_present_when_written() -> None:
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    atoms.set_masses([2.014, 2.014])  # deuterium: a real, non-derived masses array
    frame, _ = _row((atoms, {}, {}))
    assert frame.atoms.masses is not None
    np.testing.assert_allclose(frame.atoms.masses, [2.014, 2.014])


def test_pbc_taken_verbatim_from_a_real_cell() -> None:
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[4.0, 5.0, 6.0], pbc=[True, False, True])
    frame, _ = _row((atoms, {}, {}))
    assert frame.cell is not None
    np.testing.assert_allclose(np.diag(frame.cell.lattice_vectors), [4.0, 5.0, 6.0])
    assert frame.cell.pbc == (True, False, True)


def test_velocities_unit_converted_from_momenta() -> None:
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    v_ase = np.array([[0.5, 0.0, 0.0]])
    atoms.set_velocities(v_ase)  # stores momenta = mass * v internally
    frame, _ = _row((atoms, {}, {}))
    assert frame.dynamics.velocities is not None
    np.testing.assert_allclose(frame.dynamics.velocities, v_ase * ase_units.fs)


def test_initial_charges_and_magmoms_map_to_electronic() -> None:
    atoms = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    atoms.set_initial_charges([-0.3, 0.3])
    atoms.set_initial_magnetic_moments([1.0, -1.0])
    frame, _ = _row((atoms, {}, {}))
    assert frame.electronic.charges is not None
    assert frame.electronic.magnetic_moments is not None
    np.testing.assert_allclose(frame.electronic.charges, [-0.3, 0.3])
    np.testing.assert_allclose(frame.electronic.magnetic_moments, [1.0, -1.0])


def test_energy_and_forces_map_to_canonical_fields() -> None:
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]])
    atoms.calc = SinglePointCalculator(atoms, energy=-3.5, forces=[[0.1, 0.2, 0.3]])
    frame, _ = _row((atoms, {}, {}))
    assert frame.electronic.total_energy == -3.5
    assert frame.dynamics.forces is not None
    np.testing.assert_allclose(frame.dynamics.forces[0], [0.1, 0.2, 0.3])


def test_stress_carried_not_mapped_to_electronic_stress() -> None:
    # Sign-convention safety (D18): stress is carried verbatim, not mapped.
    atoms = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[3.0, 3.0, 3.0], pbc=True)
    atoms.calc = SinglePointCalculator(atoms, stress=[1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
    obj = parse_bytes(_parser(), _db_bytes((atoms, {}, {})), filename="sample.db").canonical
    assert obj.frames[0].electronic.stress is None
    assert "ase_db:stress" in obj.user_metadata.custom_per_frame


def test_fixatoms_maps_to_fixed_atoms_constraint() -> None:
    atoms = Atoms("H3", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9], [0.0, 0.0, 1.8]])
    atoms.set_constraint(FixAtoms(indices=[0, 2]))
    frame, _ = _row((atoms, {}, {}))
    assert frame.dynamics.constraints is not None
    assert frame.dynamics.constraints[0].kind == "fixed_atoms"
    assert frame.dynamics.constraints[0].atom_indices == [0, 2]


# --- key–value carry (carried, never interpreted) -------------------------------------


def test_key_value_pairs_carried_into_custom_global_with_warnings() -> None:
    result = parse_bytes(
        _parser(),
        _db_bytes((_bare(), {"label": "relaxed", "steps": 42}, {})),
        filename="sample.db",
    )
    obj = result.canonical
    assert obj.user_metadata.custom_global == {
        "ase_db:label": "relaxed",
        "ase_db:steps": 42,
    }
    carried = [i for i in result.issues if i.code == "ASEDB_KV_CARRIED"]
    assert len(carried) == 2


def test_data_blob_carried_into_custom_global() -> None:
    result = parse_bytes(
        _parser(), _db_bytes((_bare(), {}, {"note": [1, 2, 3]})), filename="sample.db"
    )
    assert result.canonical.user_metadata.custom_global == {"ase_db:data": {"note": [1, 2, 3]}}
    assert any(i.code == "ASEDB_KV_CARRIED" for i in result.issues)


# --- the multi-row refusal + asedb_row_selection (the M55 spine) -----------------------


def _two_rows() -> bytes:
    a = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    b = Atoms("He", positions=[[0.0, 0.0, 0.0]])
    return _db_bytes((a, {"label": "first"}, {}), (b, {"label": "second"}, {}))


def test_multi_row_db_refuses_on_the_single_file_path() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_bytes(_parser(), _two_rows(), filename="sample.db")
    assert excinfo.value.issues[0].code == "ASEDB_MULTIPLE_ROWS"
    assert excinfo.value.issues[0].recovery_hint == "asedb_multiple_rows"
    assert excinfo.value.issues[0].location == "rows 2"
    assert "2 rows" in excinfo.value.issues[0].message
    assert "asedb_row_selection" in excinfo.value.issues[0].message
    assert "--batch" in excinfo.value.issues[0].message


def _multi_row_refusal() -> ParseError:
    try:
        parse_bytes(_parser(), _two_rows(), filename="sample.db")
    except ParseError as exc:
        return exc
    raise AssertionError("expected ASEDB_MULTIPLE_ROWS")


def test_multi_row_refusal_is_recoverable_and_names_both_resolutions() -> None:
    exc = _multi_row_refusal()
    assert exc.issues[0].code == "ASEDB_MULTIPLE_ROWS"
    assert exc.issues[0].severity == "error"
    assert exc.issues[0].recovery_hint == "asedb_multiple_rows"
    assert exc.issues[0].location == "rows 2"
    assert "asedb_row_selection" in exc.issues[0].message
    assert "--batch" in exc.issues[0].message


def test_asedb_row_selection_resolves_to_that_one_row() -> None:
    # Resolving index,row=<i> re-parses exactly that row — scientifically equal to converting
    # that row alone (a 1-row database holding only row i).
    parser = _parser()
    data = _two_rows()
    specs = _two_rows_spec()
    for i in (0, 1):
        result = parser.parse_recover(
            io.BytesIO(data),
            filename="sample.db",
            hint="asedb_multiple_rows",
            choice="index",
            parameters={"row": i},
        )
        alone = parse_bytes(parser, _db_bytes(specs[i]), filename="sample.db")
        assert result.canonical.frames[0].atoms.symbols == alone.canonical.frames[0].atoms.symbols
        assert result.canonical.user_metadata.custom_global == (
            alone.canonical.user_metadata.custom_global
        )
        assert any(issue.code == "ASEDB_ROW_SELECTED" for issue in result.issues)


def _two_rows_spec() -> list[Row]:
    a = Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.9]])
    b = Atoms("He", positions=[[0.0, 0.0, 0.0]])
    return [(a, {"label": "first"}, {}), (b, {"label": "second"}, {})]


def test_asedb_row_selection_out_of_range_refuses() -> None:
    with pytest.raises(ParseError) as excinfo:
        _parser().parse_recover(
            io.BytesIO(_two_rows()),
            filename="sample.db",
            hint="asedb_multiple_rows",
            choice="index",
            parameters={"row": 5},
        )
    assert excinfo.value.issues[0].code == "ASEDB_MULTIPLE_ROWS"


def test_asedb_row_selection_all_is_the_batch_fan_out_not_a_single_file_resolution() -> None:
    # `all` is offered (the refusal report shows it) but resolving it on the single-file path
    # refuses: N rows can never become one Canonical Object (constant-N, Part 2 §3.2).
    with pytest.raises(ParseError) as excinfo:
        _parser().parse_recover(
            io.BytesIO(_two_rows()),
            filename="sample.db",
            hint="asedb_multiple_rows",
            choice="all",
            parameters={},
        )
    assert excinfo.value.issues[0].code == "ASEDB_MULTIPLE_ROWS"
    assert "--batch" in excinfo.value.issues[0].message


# --- empty / malformed -----------------------------------------------------------------


def test_empty_db_refuses_asedb_empty() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        connect(tmp.name, use_lock_file=False)
        tmp.flush()
        data = Path(tmp.name).read_bytes()
    with pytest.raises(ParseError) as excinfo:
        parse_bytes(_parser(), data, filename="sample.db")
    assert excinfo.value.issues[0].code == "ASEDB_EMPTY"


def test_non_sqlite_bytes_refuse_asedb_malformed() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_bytes(_parser(), b"this is not a sqlite database at all", filename="sample.db")
    assert excinfo.value.issues[0].code == "ASEDB_MALFORMED"


# --- ASE-version canary (D59) ----------------------------------------------------------


def _ase_pin() -> Requirement:
    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    for dep in pyproject["project"]["dependencies"]:
        req = Requirement(dep)
        if req.name == "ase":
            return req
    raise AssertionError("no 'ase' dependency found in pyproject.toml")


def test_installed_ase_satisfies_the_declared_pin() -> None:
    assert _ase_pin().specifier.contains(Version(ase.__version__), prereleases=True)


def test_wrapped_ase_version_is_recorded_in_provenance() -> None:
    obj = parse_bytes(_parser(), _db_bytes((_bare(), {}, {})), filename="sample.db").canonical
    parser_version = obj.provenance.history[0].parser_version
    assert parser_version is not None
    assert parser_version.startswith("ase_db-parser")
    assert f"ase {ase.__version__}" in parser_version
