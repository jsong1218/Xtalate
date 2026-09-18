"""The analysis runner: the contract, structural containment, and ``analyze`` provenance (M68-S1).

The third plugin kind (``AnalysisPlugin``, Part 2 §6 / Part 3 §2) is proven here against an in-tree
toy plugin — no packaging, no discovery, no real science — because the two guarantees v1.8 consumes
are structural and have to hold *before* any reference or third-party plugin exists:

* **Containment (D268)** — only the plugin's own ``"<name>:"`` keys reach ``user_metadata``; every
  escape attempt (an un-namespaced key, a canonical scientific path, another plugin's namespace) is
  a reported ``AnalysisError`` with the object untouched, and the plugin cannot mutate the source
  even in principle (it is handed a deep copy).
* **Provenance (D269)** — every run appends a ``ConversionRecord(operation="analyze")`` naming the
  plugin, its version, and the keys it wrote.
* **No conversion coupling** — the object that comes back differs from the one that went in in
  exactly two places: the plugin's keys in ``user_metadata.custom_global`` and the appended record.
  Nothing outside ``user_metadata`` is ever touched (analysis is annotation, not a pipeline step).
"""

from __future__ import annotations

import json
from typing import Any, cast

import numpy as np
import pytest

import xtalate
from tests._dummy_plugins import DummyAnalysis
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    CanonicalObject,
    ConversionRecord,
    Frame,
    Provenance,
    UserMetadata,
)
from xtalate.sdk import AnalysisError, AnalysisPlugin, run_analysis


def _obj() -> CanonicalObject:
    """A two-atom object carrying an existing carry-through key and a prior history record, so
    the merge and the append are exercised against pre-existing content, not an empty object."""
    atom = AtomsBlock(
        symbols=["O", "H"],
        positions=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
    )
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
        user_metadata=UserMetadata(custom_global={"xyz:comment": "from the source file"}),
    )


def _json(obj: CanonicalObject) -> dict[str, Any]:
    """The object as plain JSON-comparable data (arrays become lists), so two objects can be
    compared field by field without numpy's ambiguous element-wise ``==``."""
    return cast("dict[str, Any]", json.loads(obj.model_dump_json()))


# --- the contract ---------------------------------------------------------------------


def test_analysis_plugin_is_abstract() -> None:
    with pytest.raises(TypeError):
        AnalysisPlugin()  # type: ignore[abstract]


def test_a_plugin_declares_only_a_name_a_version_and_one_method() -> None:
    # The afternoon-implementable bar (D267): the concrete surface is exactly these three names —
    # no lifecycle hook, no configuration schema, no capability negotiation to implement.
    plugin = DummyAnalysis("toy", version="1.2.3", results={"toy:x": 1})
    assert (plugin.name, plugin.version) == ("toy", "1.2.3")
    # Two declared attributes and one method — nothing else is on the contract to implement.
    assert set(AnalysisPlugin.__annotations__) == {"name", "version"}
    assert {attr for attr in vars(AnalysisPlugin) if not attr.startswith("_")} == {"analyze"}


# --- the happy path: annotate the namespace, record the run ----------------------------


def test_run_writes_only_the_plugins_namespace_and_touches_nothing_else() -> None:
    """Ambient regression guard: outside ``user_metadata`` and the appended record, the object is
    byte-identical to what went in — analysis annotates, it never converts (P5, P6)."""
    original = _obj()
    before = _json(original)

    annotated = run_analysis(
        original,
        DummyAnalysis("toy", results={"toy:atom_count": 2, "toy:has_cell": False}),
    )
    after = _json(annotated)

    assert after["frames"] == before["frames"]
    assert after["simulation"] == before["simulation"]
    assert after["trajectory"] == before["trajectory"]
    assert after["schema_version"] == before["schema_version"]
    assert after["provenance"]["source_format"] == before["provenance"]["source_format"]
    assert after["provenance"]["source_units"] == before["provenance"]["source_units"]
    assert after["provenance"]["original_coordinate_system"] == "cartesian"
    assert after["user_metadata"]["tags"] == before["user_metadata"]["tags"]
    assert after["user_metadata"]["annotations"] == before["user_metadata"]["annotations"]
    # custom_per_atom relocated onto each frame in schema 2.0.0 (M72); its untouched-ness is already
    # covered by the frames byte-equality asserted above.
    assert after["user_metadata"]["custom_per_frame"] == before["user_metadata"]["custom_per_frame"]

    # The annotation, and nothing but the annotation, in the plugin's own namespace.
    assert annotated.user_metadata.custom_global == {
        "xyz:comment": "from the source file",  # another namespace: preserved verbatim
        "toy:atom_count": 2,
        "toy:has_cell": False,
    }
    # The prior history is intact and exactly one record was appended.
    assert after["provenance"]["history"][:-1] == before["provenance"]["history"]
    assert len(annotated.provenance.history) == len(original.provenance.history) + 1


def test_a_rerun_overwrites_only_the_plugins_own_keys() -> None:
    """A plugin owns its namespace, so a second run replaces its own keys and leaves every other
    entry (user, parser, or a neighbouring plugin) alone."""
    first = run_analysis(_obj(), DummyAnalysis("toy", results={"toy:score": 1}))
    other = run_analysis(first, DummyAnalysis("other", results={"other:score": 99}))

    again = run_analysis(other, DummyAnalysis("toy", results={"toy:score": 2}))

    assert again.user_metadata.custom_global == {
        "xyz:comment": "from the source file",
        "toy:score": 2,
        "other:score": 99,
    }


def test_the_run_appends_an_analyze_record_naming_plugin_version_and_keys() -> None:
    annotated = run_analysis(
        _obj(), DummyAnalysis("toy", version="0.1.0", results={"toy:b": 2, "toy:a": 1})
    )

    record = annotated.provenance.history[-1]
    assert record.operation == "analyze"
    assert record.parser_version == "toy 0.1.0"  # the plugin that ran, and its version
    assert record.source_format == "xyz"  # analysis is not a conversion: no target format
    assert record.target_format is None
    assert record.tool_version == xtalate.__version__
    # The keys it wrote, named in the record (sorted, so the record is deterministic).
    assert record.assumptions == ["analysis plugin 'toy' 0.1.0 wrote custom_global: toy:a, toy:b"]


def test_a_plugin_that_writes_no_keys_still_records_its_run() -> None:
    """An analysis run that found nothing to say is still a run: the record says so rather than
    leaving the invocation invisible (D269)."""
    annotated = run_analysis(_obj(), DummyAnalysis("toy", results={}))

    assert annotated.user_metadata.custom_global == {"xyz:comment": "from the source file"}
    assert annotated.provenance.history[-1].assumptions == [
        "analysis plugin 'toy' 0.1.0 wrote custom_global: no keys"
    ]


def test_analyze_joins_the_reserved_operation_vocabulary() -> None:
    """``operation`` is a plain ``str`` and ``"analyze"`` is a *documented* value on it (D269) —
    recording it changes no schema shape, so it did not itself move ``SCHEMA_VERSION`` (the bump to
    2.0.0 is M72's constant-N/custom_per_atom relocation, unrelated to the analysis vocabulary)."""
    assert SCHEMA_VERSION == "2.0.0"
    assert ConversionRecord.model_fields["operation"].annotation is str
    assert run_analysis(_obj(), DummyAnalysis("toy")).provenance.history[-1].operation == "analyze"


# --- containment, adversarially (D268) ------------------------------------------------


@pytest.mark.parametrize(
    ("key", "why"),
    [
        ("count", "an un-namespaced key (reserved for end users)"),
        ("atoms.positions", "a canonical scientific path"),
        ("other:score", "another plugin's namespace"),
        ("toy", "a bare namespace with no key"),
    ],
)
def test_every_escape_attempt_is_a_reported_error_and_the_object_is_untouched(
    key: str, why: str
) -> None:
    original = _obj()
    before = _json(original)

    with pytest.raises(AnalysisError, match=r"outside its 'toy:' namespace"):
        run_analysis(original, DummyAnalysis("toy", results={key: 1}))

    assert _json(original) == before, f"{why} must leave the object untouched"


def test_one_illegal_key_rejects_the_whole_result_rather_than_half_merging() -> None:
    """Containment is checked before anything is merged, so there is no partial annotation
    state to reason about (an all-or-nothing plugin error)."""
    original = _obj()

    with pytest.raises(AnalysisError, match=r"'atoms.positions'"):
        run_analysis(original, DummyAnalysis("toy", results={"toy:good": 1, "atoms.positions": []}))

    assert original.user_metadata.custom_global == {"xyz:comment": "from the source file"}
    assert [r.operation for r in original.provenance.history] == ["parse"]


def test_the_plugin_cannot_mutate_the_source_object() -> None:
    """The read-only view: the plugin is handed a deep copy, so a mutation it makes — to a
    scientific array, to user metadata, to provenance — cannot reach the caller's object."""

    def vandalize(view: CanonicalObject) -> None:
        view.frames[0].atoms.symbols.append("X")
        view.frames[0].atoms.positions[0, 0] = 99.0
        view.user_metadata.custom_global["toy:injected"] = "sneaked in"
        view.provenance.source_format = "hijacked"

    original = _obj()
    before = _json(original)

    annotated = run_analysis(
        original, DummyAnalysis("toy", results={"toy:ok": True}, mutate=vandalize)
    )

    assert _json(original) == before
    # Only what the plugin *returned* was merged — not what it wrote into its view.
    assert annotated.user_metadata.custom_global == {
        "xyz:comment": "from the source file",
        "toy:ok": True,
    }
    assert annotated.provenance.source_format == "xyz"


def test_a_crashing_plugin_is_reported_as_a_plugin_error() -> None:
    """Failure containment at run time: a crashing plugin is its own reported failure, naming
    the plugin, never an opaque traceback that looks like a defect in Xtalate."""
    original = _obj()
    before = _json(original)

    with pytest.raises(
        AnalysisError, match=r"analysis plugin 'toy' \(0.1.0\) raised RuntimeError: boom"
    ):
        run_analysis(original, DummyAnalysis("toy", raises=RuntimeError("boom")))

    assert _json(original) == before


def test_a_value_the_container_cannot_hold_is_a_reported_error() -> None:
    """``custom_global`` is shape-validated and serializability-checked (Part 2 §6 rule 1), and a
    plugin's values get the same validation a parser's carry-through gets — reported against the
    plugin that produced them, not left to surface at serialization time."""
    original = _obj()

    with pytest.raises(AnalysisError, match=r"'toy:'|cannot hold"):
        run_analysis(original, DummyAnalysis("toy", results={"toy:bad": object()}))  # type: ignore[dict-item]

    assert original.user_metadata.custom_global == {"xyz:comment": "from the source file"}
