"""Analysis results are the plugin's *own* entries, never a post-merge prefix rescan (v2.0 S6).

Before this fix the runner and CLI rebuilt the ``results`` payload by scanning
``user_metadata.custom_global`` for keys prefixed ``"<name>:"`` *after* the merge — so a
pre-existing carry-through key that happened to share the plugin's namespace (a parser whose
``format_id`` collides with the plugin ``name``) was swept into "results" and mis-attributed to
the plugin. ``run_analysis`` already knows the exact keys the plugin wrote; it now returns them
as :class:`~xtalate.sdk.analysis.AnalysisRun.entries`, and the registry refuses a plugin whose
name could collide in the first place.
"""

from __future__ import annotations

import numpy as np
import pytest

import xtalate
from tests._dummy_plugins import DummyAnalysis
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    ConversionRecord,
    Frame,
    Provenance,
    UserMetadata,
)
from xtalate.sdk import run_analysis


def _obj_with_colliding_carry_through() -> CanonicalObject:
    """A two-atom object whose ``custom_global`` already carries a ``"probe:pre"`` key — the
    carry-through a parser named ``probe`` would leave — so the merge runs against a pre-existing
    key sharing the plugin's namespace."""
    atom = AtomsBlock(symbols=["O", "H"], positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]))
    return CanonicalObject(
        frames=[Frame(index=0, atoms=atom)],
        provenance=Provenance(
            source_filename="water.xyz",
            source_format="xyz",
            source_units={"positions": "angstrom"},
            original_coordinate_system="cartesian",
            history=[
                ConversionRecord(
                    timestamp="2026-09-10T00:00:00Z",
                    operation="parse",
                    source_format="xyz",
                    target_format=None,
                    tool_version=xtalate.__version__,
                    parser_version=f"xyz-parser {xtalate.__version__}",
                    assumptions=[],
                )
            ],
        ),
        user_metadata=UserMetadata(custom_global={"probe:pre": 1}),
    )


def test_results_are_exactly_the_plugin_entries_not_a_prefix_rescan() -> None:
    obj = _obj_with_colliding_carry_through()
    plugin = DummyAnalysis("probe", results={"probe:out": 2})

    run = run_analysis(obj, plugin)

    # The entries are exactly what the plugin wrote — the pre-existing carry-through key that
    # shares the namespace is NOT attributed to the plugin.
    assert run.entries == {"probe:out": 2}
    assert "probe:pre" not in run.entries

    # The annotated object still carries both keys (the merge is a superset), so nothing is lost —
    # the fix is purely about *attribution*, not about dropping the carry-through.
    assert run.canonical.user_metadata.custom_global == {"probe:pre": 1, "probe:out": 2}


def test_a_plugin_that_writes_no_keys_reports_empty_entries() -> None:
    run = run_analysis(_obj_with_colliding_carry_through(), DummyAnalysis("probe", results={}))
    assert run.entries == {}
    # The pre-existing key survives on the object but is never claimed as a result.
    assert run.canonical.user_metadata.custom_global == {"probe:pre": 1}


def test_analysis_run_exposes_the_annotated_object() -> None:
    run = run_analysis(_obj_with_colliding_carry_through(), DummyAnalysis("probe", results={}))
    # The appended ``analyze`` record rides the returned object, not the entries mapping.
    assert run.canonical.provenance.history[-1].operation == "analyze"
    with pytest.raises(AttributeError):
        _ = run.entries.provenance  # type: ignore[attr-defined]
