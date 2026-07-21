"""Identity round-trips (Part 3 §3): ``A → Canonical → A' → Canonical'`` must reproduce the
scientific content exactly. This is the first end-to-end proof that a format's parser and
exporter agree — "the project works" checkpoint of the implementation plan.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

from tests._format_helpers import assert_scientifically_equal, parse_bytes
from tests.roundtrip import _matrix
from tests.roundtrip._compare import assert_equal_over_subspace
from xtalate.exporters.ase_traj import make_ase_traj_exporter
from xtalate.exporters.cif import make_cif_exporter
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.exporters.poscar import make_contcar_exporter, make_poscar_exporter
from xtalate.exporters.xyz import XyzExporter
from xtalate.parsers.ase_traj import make_ase_traj_parser
from xtalate.parsers.cif import make_cif_parser
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.parsers.poscar import make_contcar_parser, make_poscar_parser
from xtalate.parsers.xyz import XyzParser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.sdk import ExporterPlugin, ParserPlugin
from xtalate.validation import ToleranceProfile

GOLDEN = Path(__file__).parent.parent / "golden"
_STRICT = ToleranceProfile.named("strict")


def _roundtrip(parser: ParserPlugin, exporter: ExporterPlugin, source: bytes) -> None:
    first = parse_bytes(parser, source).canonical
    buf = io.BytesIO()
    exporter.export(first, buf)
    second = parse_bytes(parser, buf.getvalue()).canonical
    assert_scientifically_equal(first, second)


def test_xyz_identity() -> None:
    source = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    _roundtrip(XyzParser(), XyzExporter(), source)


def test_poscar_identity() -> None:
    source = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    _roundtrip(make_poscar_parser(), make_poscar_exporter(), source)


def test_extxyz_identity() -> None:
    source = (GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz").read_bytes()
    _roundtrip(ExtxyzParser(), ExtxyzExporter(), source)


def test_ase_traj_identity() -> None:
    source = (GOLDEN / "ase_traj" / "co-relax-3frame" / "relax.traj").read_bytes()
    _roundtrip(make_ase_traj_parser(), make_ase_traj_exporter(), source)


# --- CIF: the one format whose identity round-trip is deliberately lossy (M19, D68) ------------

CIF_SOURCE = GOLDEN / "cif" / "zno-hexagonal-p1" / "zno_hexagonal.cif"


def test_cif_identity_loses_exactly_the_space_group_symbol_and_nothing_else() -> None:
    """CIF cannot use ``_roundtrip``, and the reason is the milestone's central decision rather
    than a defect. Xtalate writes the identity operation and every atom explicitly, emitting **no**
    space-group symbol (D68), so ``cell.space_group`` is the one canonical field that does not come
    back. Asserting bare equality would fail; asserting nothing would let a real regression hide.

    So this pins both halves. Which field is allowed to vanish is **derived from the Capability
    Matrix**, not hand-listed here — it is exactly the set of source-present paths CIF's write side
    declares ``NONE``, the same computation the two-hop suite uses. If a future change made CIF drop
    something else, or made it stop declaring the drop, that set would no longer be
    ``{'cell.space_group'}`` and this fails. Everything outside that set must be equal outright.
    """
    parser, exporter = make_cif_parser(), make_cif_exporter()
    first = parse_bytes(parser, CIF_SOURCE.read_bytes()).canonical
    buf = io.BytesIO()
    exporter.export(first, buf)
    second = parse_bytes(parser, buf.getvalue()).canonical

    # The fixture must actually carry a symbol, or the rest of this proves nothing.
    assert first.frames[0].cell is not None
    assert first.frames[0].cell.space_group == "P 1"

    matrix = default_registry().capability_matrix()
    present = first.field_presence().present_paths()
    lost = _matrix.unexpressible_source_paths(matrix, present, "cif")
    assert lost == {"cell.space_group"}, (
        "CIF's declared write-side losses changed; D68 accounts for the space-group symbol only"
    )

    # Declared and actual agree: the symbol is gone, not merely undeclared.
    assert second.frames[0].cell is not None
    assert second.frames[0].cell.space_group is None

    # And the loss stops there. Compared over the matrix's own round-trip equality set, which
    # excludes `cell.space_group` for free (it is NONE on the write side) rather than by a hand
    # exclusion here. Tolerance-based, not exact: CIF's native form is cell *parameters*, so a
    # round-trip runs lengths/angles → vectors → lengths/angles and lands a few ulp away.
    assert_equal_over_subspace(
        first, second, _matrix.comparable_subspace(matrix, "cif", "cif"), _STRICT
    )

    # The FULL-only subspace above says nothing about the `cif:` carry-through columns, which are
    # PARTIAL — and they are most of what M19 added, so they get their own assertion.
    assert first.user_metadata.custom_per_atom.keys() == second.user_metadata.custom_per_atom.keys()
    assert (
        second.user_metadata.custom_per_atom["cif:atom_site_label"]
        == first.user_metadata.custom_per_atom["cif:atom_site_label"]
    )
    assert second.user_metadata.custom_global == first.user_metadata.custom_global


def test_cif_export_reaches_its_fixed_point_at_the_first_hop() -> None:
    """The practical payoff of writing no symbol (D68): hop 1 drops ``cell.space_group``, and every
    later hop has nothing left to drop. Writing ``P 1`` instead would have had hop 1 *introduce* a
    field that hop 2 then preserved — a chain whose canonical content kept moving after the first
    step, which is much harder to reason about than one that settles immediately.

    Stated over the *presence map* rather than the output bytes, deliberately. Byte equality is not
    achievable and asserting it would be asserting something false: CIF stores a cell as lengths and
    angles, so each hop rebuilds vectors from parameters and derives parameters back, and
    ``_cell_length_b`` wanders into its last ulp (3.0 → 3.0000000000000004) while the cell it
    describes is unchanged. What must not move is *which fields exist* — that is the actual claim.
    """
    parser, exporter = make_cif_parser(), make_cif_exporter()

    def write(obj: CanonicalObject) -> bytes:
        buf = io.BytesIO()
        exporter.export(obj, buf)
        return buf.getvalue()

    source = parse_bytes(parser, CIF_SOURCE.read_bytes()).canonical
    hop1 = parse_bytes(parser, write(source)).canonical
    hop2 = parse_bytes(parser, write(hop1)).canonical

    # Hop 1 is where the symbol goes, and it is the only presence change from the source.
    assert set(source.field_presence().present_paths()) - set(
        hop1.field_presence().present_paths()
    ) == {"cell.space_group"}

    # From there the presence map is a fixed point — hop 2 neither loses nor invents a field.
    assert hop1.field_presence().present_paths() == hop2.field_presence().present_paths()
    matrix = default_registry().capability_matrix()
    assert_equal_over_subspace(
        hop1, hop2, _matrix.comparable_subspace(matrix, "cif", "cif"), _STRICT
    )


SELECTIVE = b"""sd test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
2
Selective dynamics
Direct
  0.0 0.0 0.0   T T F
  0.5 0.5 0.5   F F F
"""

SELECTIVE_ALL_T = b"""all-T test
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
1
Selective dynamics
Direct
  0.0 0.0 0.0   T T T
"""

CONTCAR_WITH_VELOCITIES = b"""md restart
1.0
  4.0  0.0  0.0
  0.0  4.0  0.0
  0.0  0.0  4.0
H
2
Direct
  0.0 0.0 0.0
  0.5 0.5 0.5

Cartesian
  0.10 0.20 0.30
  0.40 0.50 0.60
"""


def test_poscar_selective_dynamics_identity() -> None:
    _roundtrip(make_poscar_parser(), make_poscar_exporter(), SELECTIVE)


def test_poscar_all_true_selective_dynamics_roundtrips_as_empty_list() -> None:
    parser, exporter = make_poscar_parser(), make_poscar_exporter()
    first = parse_bytes(parser, SELECTIVE_ALL_T).canonical
    assert first.frames[0].dynamics.constraints == []
    buf = io.BytesIO()
    exporter.export(first, buf)
    second = parse_bytes(parser, buf.getvalue()).canonical
    # The [] vs None distinction survives (Part 3 §3 n.7).
    assert second.frames[0].dynamics.constraints == []


def test_contcar_velocity_identity() -> None:
    _roundtrip(make_contcar_parser(), make_contcar_exporter(), CONTCAR_WITH_VELOCITIES)
    obj = parse_bytes(make_contcar_parser(), CONTCAR_WITH_VELOCITIES).canonical
    assert obj.frames[0].dynamics.velocities is not None
    assert np.array_equal(obj.frames[0].dynamics.velocities[1], [0.4, 0.5, 0.6])


def test_poscar_exporter_refuses_multiframe() -> None:
    # Reducing a trajectory to one structure is the engine's recorded choice, not a silent
    # exporter truncation (Part 4 §3).
    traj = parse_bytes(XyzParser(), (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes())
    multi: CanonicalObject = traj.canonical
    with pytest.raises(ValueError, match="single structure"):
        make_poscar_exporter().export(multi, io.BytesIO())
