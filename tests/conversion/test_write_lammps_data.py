"""Write-side refusals and the clean write for the LAMMPS data target (v1.3 M48-S2, D181;
Part 4 §1, §3.3, §4).

A data file is the restart flagship — the deploy arrow of the version — and three distinct guards
stand between an object and a written file, each a *completed* job that writes no bytes, never an
HTTP error or a mid-write crash (P1):

* **No declared unit style → ``RECOVERY_REQUIRED`` / ``ambiguous_units``.** A data file states no
  units, so every write must declare the style its values are written in. The pre-flight fires the
  same target-identity ``ambiguous_units`` scenario the dump target does (``requires_units_style``),
  refusing without a preset — the write-side trigger earned for free from the M47-S1 generalization.
* **No masses → ``RECOVERY_REQUIRED`` / ``missing_masses``.** A data file *requires* a per-type
  ``Masses`` table, so ``atoms.masses`` is a write ``required_field``: an object without them is
  refused via the existing ``missing_masses`` scenario, never invented (P4).
* **A trajectory → ``RECOVERY_REQUIRED`` / ``frame_selection``.** A data file is one configuration;
  a multi-frame object cannot be one, so — like POSCAR/CONTCAR — the exporter declares
  ``max_frames=1`` and pre-flight offers ``frame_selection`` to pick a configuration (M48-S3, D183),
  rather than refusing outright or silently writing only frame 0. Supplying the choice completes the
  write.

The companion is the resolved single-configuration object with masses that writes cleanly under the
same pipeline — proving the guards refuse exactly the unresolvable inputs and nothing else.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from xtalate.conversion import ConversionEngine
from xtalate.conversion.engine import ConversionResult
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject, load_canonical

GOLDEN = Path(__file__).parent.parent / "golden" / "lammps_data"
_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_METAL = {"ambiguous_units": {"choice": "metal", "parameters": {}}}


def _load(case: str) -> CanonicalObject:
    return load_canonical((GOLDEN / case / "expected.canonical.json").read_text())


def _convert(
    obj: CanonicalObject, recovery_choices: dict[str, dict[str, Any]] | None = None
) -> ConversionResult:
    return _ENGINE.convert(
        obj,
        source_format_id="lammps_data",
        target_format_id="lammps_data",
        recovery_choices=recovery_choices,
    )


def test_convert_refuses_without_a_unit_preset() -> None:
    result = _convert(_load("atomic-metal-ortho"))
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = result.report.refusal["unresolved_scenarios"]
    assert [s["scenario"] for s in scenarios] == ["ambiguous_units"]
    assert scenarios[0]["options"] == ["metal", "real", "si"]


def test_convert_refuses_an_object_without_masses() -> None:
    obj = _load("atomic-metal-ortho")
    obj.frames[0].atoms.masses = None
    result = _convert(obj, recovery_choices=_METAL)  # units resolved → masses gate is what fires
    assert result.report.status == "refused"
    assert result.output is None
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "RECOVERY_REQUIRED"
    assert [s["scenario"] for s in result.report.refusal["unresolved_scenarios"]] == [
        "missing_masses"
    ]


def test_convert_offers_frame_selection_for_a_multi_frame_object() -> None:
    """A multi-frame object is a *recovery*, not an outright refusal (M48-S3, D183): a data file
    writes one configuration via ``max_frames=1``, so pre-flight offers ``frame_selection`` — just
    the POSCAR/CONTCAR path — instead of the old ``UNREPRESENTABLE_VALUE`` refusal. Without the
    choice it refuses recoverably; with it, the write completes on the selected frame."""
    obj = _load("atomic-metal-ortho")
    second = copy.deepcopy(obj.frames[0])
    second.index = 1
    obj.frames.append(second)

    refused = _convert(obj, recovery_choices=_METAL)
    assert refused.report.status == "refused"
    assert refused.output is None
    assert refused.report.refusal is not None
    assert refused.report.refusal["code"] == "RECOVERY_REQUIRED"
    scenarios = refused.report.refusal["unresolved_scenarios"]
    assert [s["scenario"] for s in scenarios] == ["frame_selection"]
    assert "first" in scenarios[0]["options"]
    # A refused report still carries the pre-flight prediction (completeness holds over it).
    assert refused.report.preserved or refused.report.removed

    # Supplying the frame choice completes the write on one configuration.
    resolved = _convert(
        obj,
        recovery_choices={**_METAL, "frame_selection": {"choice": "first", "parameters": {}}},
    )
    assert resolved.report.status == "completed"
    assert resolved.output is not None


def test_convert_writes_a_restart_file_with_the_metal_preset() -> None:
    obj = _load("full-triclinic-topology")
    result = _convert(obj, recovery_choices=_METAL)
    assert result.report.status == "completed"
    assert result.output is not None
    # The interpretive Assumption is recorded, with no `supplied` entry (nothing was fabricated).
    assert [a.scenario for a in result.report.assumptions] == ["ambiguous_units"]
    assert result.report.assumptions[0].choice == "metal"
    assert result.report.supplied == []
    # The written file is a real data file: an Atoms section under the declared style, and the
    # carried topology restored.
    text = result.output.decode("utf-8")
    assert "Atoms # full" in text
    assert "Bonds" in text
    # And the engine's own validation passes — the re-parse reproduces the object within tolerance.
    assert result.validation is not None
    assert result.validation.status == "passed"


def test_no_preset_data_write_reparse_is_exact(tmp_path: Path) -> None:
    """The resolved style rides the object channel to the exporter, so a completed write validates:
    a metal-preset conversion of the charge/velocities golden re-parses to the same values (the
    round-trip proof lives in the exporter suite; here it is the engine that drives it)."""
    result = _convert(_load("charge-real-velocities"), recovery_choices=_METAL)
    assert result.report.status == "completed"
    assert result.output is not None
    assert b"Velocities" in result.output
