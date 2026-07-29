"""``ConversionEngine.preview_recovery`` — the byte-exact Assumption preview (M31-S1, Part 6 §3.2).

The Recovery Workflow UI must show a user the *exact* ``description`` a conversion will record for
their choices *before* they confirm — consent and provenance are the same artifact (P4). That
sentence is generated inside the Recovery Engine at apply-time from the user's parameters plus
runtime values, so the browser cannot reproduce it without re-implementing engine logic (P2 /
standing rule 3 forbid that). ``preview_recovery`` runs the *real* recovery apply path and returns
the resulting report ``Assumption`` objects — byte-identical to what ``convert`` records — but stops
before export and validation, so it is cheap enough to drive a live preview.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from xtalate.capabilities import Registry
from xtalate.conversion import ConversionEngine
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.recovery import RecoveryError
from xtalate.schema import CanonicalObject

GOLDEN = Path(__file__).parent.parent / "golden"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _parse(reg: Registry, format_id: str, path: Path) -> CanonicalObject:
    return (
        reg.get_parser(format_id).parse(io.BytesIO(path.read_bytes()), filename=path.name).canonical
    )


# The flagship pair: a 2-frame, cell-less trajectory to a single-structure, periodic target needs
# both a frame_selection and a missing_lattice decision (Part 4 §5).
_FLAGSHIP = ("xyz", GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")


def test_preview_returns_the_exact_assumptions_convert_will_record() -> None:
    reg = _registry()
    source = _parse(reg, *_FLAGSHIP)
    engine = ConversionEngine(reg)
    choices: dict[str, dict[str, Any]] = {
        "frame_selection": {"choice": "last"},
        "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
    }

    preview = engine.preview_recovery(
        source, source_format_id="xyz", target_format_id="poscar", recovery_choices=choices
    )
    final = engine.convert(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices=choices,
        recovery_origin="user",
    )

    assert final.report.status == "completed"
    # A preview that paraphrases the record is not the record: scenario, choice, and the *exact*
    # description sentence must match the final report, in the same application order.
    assert [(a.scenario, a.choice, a.description) for a in preview.assumptions] == [
        (a.scenario, a.choice, a.description) for a in final.report.assumptions
    ]
    assert preview.unresolved == []
    # The preview stops before export/validation — it is a record preview, not a conversion.
    assert all(a.description for a in preview.assumptions)


def test_preview_reports_unresolved_scenarios_when_a_choice_is_missing() -> None:
    reg = _registry()
    source = _parse(reg, *_FLAGSHIP)
    # Only the frame chosen; the lattice decision is still owed. Resolution is all-or-nothing, so
    # no partial assumptions are invented — the preview names what remains.
    preview = ConversionEngine(reg).preview_recovery(
        source,
        source_format_id="xyz",
        target_format_id="poscar",
        recovery_choices={"frame_selection": {"choice": "last"}},
    )

    assert preview.assumptions == []
    assert [s.scenario for s in preview.unresolved] == ["missing_lattice"]


def test_preview_rejects_a_choice_the_pair_never_offered() -> None:
    reg = _registry()
    source = _parse(reg, *_FLAGSHIP)
    # A POSCAR target never offers `non_periodic` for missing_lattice — an unoffered choice is a
    # caller error the endpoint maps to INVALID_RECOVERY_CHOICE, not a silent coercion.
    with pytest.raises(RecoveryError):
        ConversionEngine(reg).preview_recovery(
            source,
            source_format_id="xyz",
            target_format_id="poscar",
            recovery_choices={
                "frame_selection": {"choice": "last"},
                "missing_lattice": {"choice": "non_periodic"},
            },
        )
