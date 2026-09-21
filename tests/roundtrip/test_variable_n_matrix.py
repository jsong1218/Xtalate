"""Variable-N two-hop matrix (M75; Part 8 §2.2, Part 4 §3.3).

The registry-driven two-hop matrix (``test_two_hop``) reads its H5MD source from the *constant-N*
``co2-nvt-3frame`` golden — it reads every source bare, and the variable-N goldens are pinned in the
dedicated suites. This suite drives the *variable-N* H5MD golden (``gcmc-variable-n-3frame``: a
grand-canonical run of 2, 3, then 4 argon atoms) as a source into **every** write-capable target, so
a genuinely per-frame-N object flows through the whole exporter axis:

* a variable-N-capable target (``supports_variable_atom_count``) converts and validates per frame;
* a constant-N-only target refuses at pre-flight, offering ``frame_selection`` — the honest way out
  (select or split), *never* padding, masking, or truncating atoms to a single N.

The target set and each target's capability are read from the registry at collection time, so a new
variable-N exporter auto-enrols on the correct side without a test edit (P6). Nightly-marked: this
is the full-width matrix, not the curated PR subset.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.roundtrip._matrix import FIXED_PRESETS, writeable_targets
from xtalate.conversion import ConversionEngine
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject
from xtalate.validation import ToleranceProfile

_REGISTRY = default_registry()
_ENGINE = ConversionEngine(_REGISTRY)
_MATRIX = _REGISTRY.capability_matrix()
_STRICT = ToleranceProfile.named("strict")
_SRC = (
    Path(__file__).resolve().parents[1] / "golden" / "h5md" / "gcmc-variable-n-3frame" / "sample.h5"
)

# Every write-capable target, split by whether it can express a variable atom count — read from the
# registry so a newly registered exporter enrols automatically (P6).
_TARGETS = writeable_targets(_REGISTRY)
# All FIXED_PRESETS *except* frame_selection: for a constant-N target we want the variable-N refusal
# itself, not a pre-resolved frame reduction — every other fabricative/selective gap stays resolved
# so a refusal can only be about the atom count.
_PRESETS_NO_FRAME_SELECTION = {k: v for k, v in FIXED_PRESETS.items() if k != "frame_selection"}


def _variable_n_source() -> CanonicalObject:
    parser = _REGISTRY.get_parser("h5md")
    with _SRC.open("rb") as fh:
        return parser.parse(io.BytesIO(fh.read()), filename=_SRC.name).canonical


@pytest.mark.nightly
@pytest.mark.parametrize("target", _TARGETS)
def test_variable_n_source_converts_or_refuses_without_ghost_atoms(target: str) -> None:
    source = _variable_n_source()
    counts = {len(fr.atoms.symbols) for fr in source.frames}
    assert len(counts) > 1, f"fixture is not variable-N: frame counts {sorted(counts)}"

    if _MATRIX.get(target, "write").supports_variable_atom_count:
        result = _ENGINE.convert(
            source,
            source_format_id="h5md",
            target_format_id=target,
            mode="permissive",
            recovery_choices=FIXED_PRESETS,
            tolerance_profile=_STRICT,
        )
        assert result.report.status != "refused", (
            f"variable-N → {target} refused: {result.report.refusal}"
        )
        assert result.validation is not None, f"variable-N → {target}: no validation report"
        problems = [
            (c.check_id, c.status)
            for c in result.validation.checks
            if c.status not in ("pass", "skipped")
        ]
        assert result.validation.status == "passed", (
            f"variable-N → {target} validation {result.validation.status}: {problems}"
        )
    else:
        result = _ENGINE.convert(
            source,
            source_format_id="h5md",
            target_format_id=target,
            mode="permissive",
            recovery_choices=_PRESETS_NO_FRAME_SELECTION,
            tolerance_profile=_STRICT,
        )
        # Honest refusal: a constant-N container cannot hold a per-frame-N trajectory, so pre-flight
        # refuses and offers frame_selection (select one frame or split per frame). It never pads or
        # truncates atoms to a single N — the no-ghost-atoms rule, exercised across the matrix.
        assert result.report.status == "refused", (
            f"variable-N → {target}: constant-N target did not refuse (status "
            f"{result.report.status}) — a silent pad/truncate would look exactly like this"
        )
        assert result.report.refusal is not None
        offered = {s["scenario"] for s in result.report.refusal["unresolved_scenarios"]}
        assert "frame_selection" in offered, (
            f"variable-N → {target}: refused but frame_selection not offered ({offered})"
        )
