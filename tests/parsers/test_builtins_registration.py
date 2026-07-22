"""The v0.1 builtin parsers/exporters register cleanly and drive the sniffer end to end.

This is the M3 counterpart of M2's dummy-plugin check: real capability declarations must
validate against the canonical schema paths (Part 3 §4.1), and the sniffer must pick the
right format for each fixture from the real ``sniff()`` scores alone (Part 3 §6.1).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.roundtrip import _matrix
from xtalate import __version__ as xtalate_version
from xtalate.capabilities import Registry
from xtalate.discovery import Sniffer
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers

GOLDEN = Path(__file__).parent.parent / "golden"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def test_builtins_register_without_error() -> None:
    reg = _registry()
    assert {p.format_id for p in reg.parsers()} == {
        "xyz",
        "extxyz",
        "poscar",
        "contcar",
        "xdatcar",
        "ase_traj",
        "cif",
    }
    # Symmetric since M19 slice 3: every format Xtalate reads it can also write. The two
    # assertions stay separate because that symmetry is a fact about the current format set, not
    # a property of the registry — a read-only format is legitimate and was the case until now.
    assert {e.format_id for e in reg.exporters()} == {
        "xyz",
        "extxyz",
        "poscar",
        "contcar",
        "xdatcar",
        "ase_traj",
        "cif",
    }


@pytest.mark.parametrize("format_id", sorted(_matrix.source_formats_with_golden()))
def test_every_builtin_records_the_package_version_in_provenance(format_id: str) -> None:
    """``parser_version`` must track the *package* version for every first-party format.

    The default in ``parsers._common.parse_record`` does that; the ``parser_version`` override
    exists for a parser that wraps something whose version belongs in provenance too (ase_traj
    folds in ``ase.__version__``, D59). CIF passed its own class attribute instead, hardcoded
    "0.4.0" — identical to the package version at the time, so every string looked right, and at
    0.5.0 CIF alone would have gone on claiming 0.4.0 in shipped provenance records.

    Driven through a real parse of each golden source, because that is the only thing that
    exercises a parser's override. An earlier draft of this test called ``parse_record`` directly
    and was therefore vacuous: it re-derived the default and asserted the default, while the
    override it existed to catch was never invoked.

    A wrapped-library suffix is allowed, so this checks the prefix; a wrong package version is not.
    """
    golden = _matrix.golden_source(format_id)
    parser = next(p for p in builtin_parsers() if p.format_id == format_id)
    canonical = parser.parse(io.BytesIO(golden.source), filename=golden.filename).canonical
    recorded = canonical.provenance.history[0].parser_version
    assert recorded is not None
    assert recorded.startswith(f"{format_id}-parser {xtalate_version}"), recorded


#: ``ase_traj`` builds its ``parser_version`` as a module-level constant at import time, folding in
#: ``ase.__version__`` (D59). That is correct — a real release bump re-imports the module and the
#: constant is rebuilt — but it means the string cannot follow a *runtime* patch, so the simulated
#: bump below would fail it for a reason that is not the defect. Its derivation from the package
#: version is covered by ``test_every_builtin_records_the_package_version_in_provenance`` above.
_LATE_BOUND_VERSION = sorted(set(_matrix.source_formats_with_golden()) - {"ase_traj"})


@pytest.mark.parametrize("format_id", _LATE_BOUND_VERSION)
def test_the_recorded_version_follows_a_release_bump(
    format_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same invariant, made falsifiable *today*.

    The test above cannot fail on the defect it exists for: CIF's hardcoded "0.4.0" happened to
    equal the package version, so every string was correct until the next bump — a bug that is
    invisible precisely while nobody is looking for it. Simulating the bump is what converts it
    from latent to observable, so this is checked now rather than discovered by a user reading
    provenance after 0.5.0 ships.
    """
    monkeypatch.setattr("xtalate.parsers._common.__version__", "9.9.9")
    golden = _matrix.golden_source(format_id)
    parser = next(p for p in builtin_parsers() if p.format_id == format_id)
    canonical = parser.parse(io.BytesIO(golden.source), filename=golden.filename).canonical
    recorded = canonical.provenance.history[0].parser_version
    assert recorded is not None
    assert recorded.startswith(f"{format_id}-parser 9.9.9"), recorded


def test_every_builtin_declares_a_plugin_version() -> None:
    # The plugin version is a different number from the release the format shipped in, and the
    # first-party set states it uniformly. CIF's parser said "0.4.0" while CIF's *exporter* said
    # "0.1.0" — the same format disagreeing with itself about what the field means.
    #
    # Collected as (side, format_id, version) triples rather than into a dict keyed by format_id:
    # the first draft did the latter, so the exporter entry overwrote the parser entry for the
    # same format and the parser version — the one actually wrong — was never examined.
    declared = [("parser", p.format_id, p.version) for p in builtin_parsers()]
    declared += [("exporter", e.format_id, e.version) for e in builtin_exporters()]
    assert [d for d in declared if d[2] != "0.1.0"] == []


def test_capability_matrix_reports_poscar_write_side() -> None:
    matrix = _registry().capability_matrix()
    caps = matrix.get("poscar", "write")
    assert caps.max_frames == 1
    assert set(caps.required_fields) == {"atoms.symbols", "atoms.positions", "cell.lattice_vectors"}
    # Wildcard 'simulation.*' expanded to concrete leaves at registration (§4.1).
    assert matrix.field_capability("poscar", "write", "simulation.temperature").level == "none"
    assert matrix.field_capability("poscar", "write", "cell.lattice_vectors").level == "full"


def test_sniffer_picks_xyz_for_xyz_file() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    result = sniffer.sniff(data, "water_traj.xyz")
    assert result.format_id == "xyz"


def test_sniffer_prefers_extxyz_over_plain_xyz_on_marked_file() -> None:
    # Both parsers accept the .xyz name, but only extXYZ recognises the Lattice=/Properties=
    # markers — the superset wins the disambiguation (Part 3 §6.1, §3 n.2).
    sniffer = Sniffer(_registry())
    data = b'1\nLattice="4 0 0 0 4 0 0 0 4" Properties=species:S:1:pos:R:3\nH 0 0 0\n'
    result = sniffer.sniff(data, "structure.xyz")
    assert result.format_id == "extxyz"


def test_sniffer_picks_plain_xyz_over_extxyz_without_markers() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xyz" / "water-traj" / "water_traj.xyz").read_bytes()
    assert sniffer.sniff(data, "water_traj.xyz").format_id == "xyz"


def test_sniffer_picks_poscar_by_name() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    result = sniffer.sniff(data, "POSCAR")
    assert result.format_id == "poscar"
    assert result.confidence == 1.0


def test_sniffer_picks_xdatcar_by_name() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xdatcar" / "nacl-md-fixed-cell" / "XDATCAR").read_bytes()
    result = sniffer.sniff(data, "XDATCAR")
    assert result.format_id == "xdatcar"
    assert result.confidence == 1.0


def test_sniffer_picks_xdatcar_over_poscar_on_nameless_trajectory() -> None:
    # A POSCAR-shaped header followed by a configuration marker is XDATCAR, not POSCAR: the
    # marker sits where POSCAR puts its coordinates, so only one reading can be right (§6.1).
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "xdatcar" / "nacl-md-fixed-cell" / "XDATCAR").read_bytes()
    assert sniffer.sniff(data, None).format_id == "xdatcar"


def test_sniffer_flags_poscar_contcar_ambiguity_on_nameless_file() -> None:
    sniffer = Sniffer(_registry())
    data = (GOLDEN / "poscar" / "nacl-primitive" / "POSCAR").read_bytes()
    result = sniffer.sniff(data, None)
    # POSCAR wins the nameless tie but the CONTCAR candidate is close => ambiguous (§6.1).
    assert result.format_id == "poscar"
    assert result.ambiguous is True
    assert {c.format_id for c in result.candidates} >= {"poscar", "contcar"}
