"""Data topology is loss-*predicted* before conversion (v1.3 M48-S3; P5, P1; Part 4 §2).

Bonds / angles / dihedrals a data file carries live in ``custom_global['lammps_data:topology']`` — a
carry no other Phase-1 or v1.3 target can express. The whole point of the Capability Matrix (P5) is
that a user learns this *before* converting: the pre-flight diff routes the topology carry to
``removed`` when the target cannot hold it, and to ``preserved`` when it can. This is the executable
version of the litmus test — if you diffed a data source against an extXYZ output by hand, the lost
Bonds section must be something Xtalate already told you about (P1), never a silent drop.

Two contrasting conversions of the same topology-bearing source prove both directions:

* **data → extXYZ** — extXYZ has no topology container, so the pre-flight *predicts the loss*: the
  topology path appears in ``removed`` on the Conversion Report.
* **data → data** — a data file round-trips its own topology carry verbatim (M48-S2), so the same
  path appears in ``preserved`` and in no ``removed`` entry — no topology loss is predicted.
"""

from __future__ import annotations

import io
from pathlib import Path

from xtalate.conversion import ConversionEngine
from xtalate.parsers.lammps_data import make_lammps_data_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_data"
_TOPOLOGY_PATH = "user_metadata.custom_global['lammps_data:topology']"
_METAL = {"ambiguous_units": {"choice": "metal", "parameters": {}}}


def _topology_source() -> CanonicalObject:
    """The full-style triclinic golden, recovered — it carries Bonds + Bond Coeffs in
    ``custom_global['lammps_data:topology']``."""
    parser = make_lammps_data_parser()
    ctx = {
        "ambiguous_units": {"choice": "metal", "parameters": {}},
        "missing_species": {"choice": "species_map", "parameters": {"species": "1:C 2:H"}},
    }
    source = parser.parse_recover(
        io.BytesIO((GOLDEN / "full-triclinic-topology" / "structure.data").read_bytes()),
        filename="structure.data",
        hint="ambiguous_units",
        choice="metal",
        parameters={},
        recovery_context=ctx,
    ).canonical
    assert "lammps_data:topology" in source.user_metadata.custom_global
    return source


def test_data_to_extxyz_predicts_topology_loss() -> None:
    """extXYZ cannot express LAMMPS topology, so the pre-flight *predicts* the loss (P5/P1): the
    topology carry is reported ``removed``, not silently dropped."""
    engine = ConversionEngine(default_registry())
    result = engine.convert(
        _topology_source(),
        source_format_id="lammps_data",
        target_format_id="extxyz",
    )
    assert result.report.status == "completed"
    removed = {e.path for e in result.report.removed}
    assert _TOPOLOGY_PATH in removed
    # And it is genuinely gone, not also claimed preserved.
    assert _TOPOLOGY_PATH not in {e.path for e in result.report.preserved}


def test_data_to_data_predicts_no_topology_loss() -> None:
    """The same source to a data target predicts *no* topology loss: the carry re-emits verbatim
    (M48-S2), so it is ``preserved`` and appears in no ``removed`` entry — the contrast that shows
    the prediction tracks the target's real capability, not a blanket 'topology is fragile' note."""
    engine = ConversionEngine(default_registry())
    result = engine.convert(
        _topology_source(),
        source_format_id="lammps_data",
        target_format_id="lammps_data",
        recovery_choices=_METAL,
    )
    assert result.report.status == "completed"
    assert _TOPOLOGY_PATH in {e.path for e in result.report.preserved}
    assert _TOPOLOGY_PATH not in {e.path for e in result.report.removed}
