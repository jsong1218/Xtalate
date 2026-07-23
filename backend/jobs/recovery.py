"""Interactive recovery — the service machinery of the ``awaiting_recovery`` pause (Part 6 §3.2).

The Recovery Engine is untouched: five versions of scenario machinery already compute honest,
pair-specific option lists (Part 4 §3.3). This module is only the *transport* — it turns a
``RECOVERY_REQUIRED`` refusal into the ``awaiting_recovery`` block the envelope carries, so a future
UI (``07_Web_UI.md §3``) renders its recovery prompt from that block alone.

Two things live here:

* :class:`RecoveryPause` — the signal the convert body raises when the conversion refused for
  ``RECOVERY_REQUIRED`` *and* the client opted into interactive recovery. The runner turns it into
  a ``running → awaiting_recovery`` transition, never a completed refused job.
* :func:`build_awaiting_block` — enriches each flat option *code* the refused report carries into
  the ``{choice, parameters_schema}`` shape the prompt renders. Enrichment only: no option is added
  or dropped, so the honesty of the computed list (no ``non_periodic`` for a POSCAR target, because
  pre-flight never offered it) is preserved exactly.
"""

from __future__ import annotations

from typing import Any

#: ``parameters_schema`` hints, keyed by ``(scenario, choice)``. The **keys** here are the parameter
#: names the Recovery Engine actually reads (``xtalate.recovery.engine``) — a client puts exactly
#: these into ``parameters`` when it resumes (M23 slice 2), so the advertised schema and the
#: consumed keys are one thing, and a prompt built from this block sends choices the engine accepts.
#: (The Part 6 §3.2 example JSON uses *illustrative* placeholder key names like ``vectors_ang``;
#: the binding contract is the engine's own param names — ``lattice``/``reference`` — so those are
#: what we advertise.) A ``(scenario, choice)`` absent from this map takes no parameters (``first``,
#: ``last``, ``non_periodic``, ``project``, ``drop_all``, ``zero_init``, ``standard_masses``, …).
_PARAMETERS_SCHEMA: dict[tuple[str, str], dict[str, str]] = {
    ("frame_selection", "index"): {"frame_index": "integer, 0-based (0..frame_count-1)"},
    ("missing_lattice", "manual_input"): {"lattice": "3×3 float — row lattice vectors, Å"},
    ("missing_lattice", "upload_reference"): {
        "reference": "file_id of a same-atom-count structure (its lattice is read)"
    },
    ("missing_lattice", "bounding_box"): {"padding_ang": "float ≥ 0 — padding on each side, Å"},
    ("missing_masses", "manual_input"): {"masses": "list[float] — one mass per atom, amu"},
    ("missing_velocities", "maxwell_boltzmann"): {
        "temperature_K": "float > 0 — sampling temperature",
        "seed": "integer — recorded for reproducibility",
    },
    ("missing_velocities", "upload_reference"): {
        "reference": "file_id of a matching structure (its velocities are read)"
    },
    ("missing_species", "species_map"): {
        "symbols": "ordered list of element symbols, one per atom"
    },
    ("missing_species", "upload_reference"): {
        "reference": "file_id of a matching structure (its symbols are read)"
    },
}


class RecoveryPause(Exception):
    """Signal that a convert job must **pause**, not refuse (Part 6 §3.2, M23).

    Raised by the worker's convert body when the conversion refused for ``RECOVERY_REQUIRED`` and
    the request set ``allow_recovery``. Carries the fully-built ``awaiting_recovery`` block (draft
    report + enriched unresolved scenarios) for the runner to persist on the ``running →
    awaiting_recovery`` edge. Distinct from an ordinary refusal (a completed job) and from an in-run
    exception (a failed job): the runner catches it explicitly, ahead of the ``failed`` path.
    """

    def __init__(self, block: dict[str, Any]) -> None:
        self.block = block
        super().__init__("job paused for interactive recovery")


def build_awaiting_block(
    *, draft_report: dict[str, Any], refusal: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the ``awaiting_recovery`` envelope block (Part 6 §3.2).

    ``draft_report`` is the pre-flight Conversion Report body (``stage='preflight'``,
    ``status='awaiting_recovery'``) — the "here's what happens once you decide" preview. ``refusal``
    is the ``RECOVERY_REQUIRED`` body from the trial ``convert``; its ``unresolved_scenarios``
    already carry the **computed** option codes for this concrete source/target pair. Each code is
    enriched into ``{choice, parameters_schema?}`` — nothing added, nothing dropped.
    """
    enriched: list[dict[str, Any]] = []
    for scenario in refusal.get("unresolved_scenarios") or []:
        code = scenario.get("scenario")
        options: list[dict[str, Any]] = []
        for choice in scenario.get("options") or []:
            option: dict[str, Any] = {"choice": choice}
            schema = _PARAMETERS_SCHEMA.get((code, choice))
            if schema is not None:
                option["parameters_schema"] = schema
            options.append(option)
        enriched.append(
            {
                "scenario": code,
                "path": scenario.get("path"),
                "detail": scenario.get("detail"),
                "options": options,
            }
        )
    return {"draft_report": draft_report, "unresolved_scenarios": enriched}
