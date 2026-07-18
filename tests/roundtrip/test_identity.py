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
from xtalate.exporters.ase_traj import make_ase_traj_exporter
from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.exporters.poscar import make_contcar_exporter, make_poscar_exporter
from xtalate.exporters.xyz import XyzExporter
from xtalate.parsers.ase_traj import make_ase_traj_parser
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.parsers.poscar import make_contcar_parser, make_poscar_parser
from xtalate.parsers.xyz import XyzParser
from xtalate.schema import CanonicalObject
from xtalate.sdk import ExporterPlugin, ParserPlugin

GOLDEN = Path(__file__).parent.parent / "golden"


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
