"""Stage-1 generator: parametrized golden mutations (MASTER_SPEC Part 8 §1.2; not a test module).

The M10 generator is **staged deliberately** (the roadmap's scope-creep mitigation, adopted as
structure). **Stage 1 — this module — is the deterministic, debuggable one:** it takes the
worked-example Canonical Objects (the committed golden ``expected.canonical.json`` files, the
same external-truth anchors the round-trip matrix uses) and systematically **nulls or populates
each optional field-path**, plus a **per-frame ``mixed`` configuration** for the multi-frame
golden, yielding a lattice of source objects. ``test_report_completeness`` drives every
``(mutant, target)`` pair through ``ConversionEngine.convert`` with fixed recovery presets and
asserts both properties (``_properties``) on each report.

Stage 2 (hypothesis strategies over randomized objects, with shrinking) is **cut for v0.2** with a
tracking issue — see ``CHANGELOG.md`` Unreleased and ``docs/DECISIONS.md`` D50. Stage 1 is the part
the plan's cut line names non-negotiable; it covers the whole optional-field lattice determin-
istically by construction.

Every mutant is a *valid* Canonical Object by construction: mutations operate on the golden's
JSON dump and re-validate through the real model validators (absence convention, constant-N,
frame-index, array shapes), so a mutation that would violate an invariant fails loudly here rather
than producing a meaningless test case.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from xtalate.schema import CanonicalObject

_GOLDEN = Path(__file__).parent.parent / "golden"

# Golden *source* objects, keyed by format_id — the worked examples of Part 8 §3. Each is the
# hand-verified expected Canonical Object the parser produces for a committed fixture; mutating
# these (rather than hand-building objects) keeps the generator anchored to real, in-spec data.
_GOLDEN_JSON: dict[str, str] = {
    "xyz": "xyz/water-traj/expected.canonical.json",
    "poscar": "poscar/nacl-primitive/expected.canonical.json",
    "extxyz": "extxyz/co-in-cell/expected.canonical.json",
}


def _base_dict(format_id: str) -> dict[str, Any]:
    text = (_GOLDEN / _GOLDEN_JSON[format_id]).read_text()
    data: dict[str, Any] = json.loads(text)
    return data


# --- Synthetic populate values -------------------------------------------------------------------
# Correct-shape, in-canonical-unit values for populating an absent field. Presence cares only about
# ``is not None`` (zeros are data, §2 rule 3), so all-zero arrays and empty constraint lists count
# as *present* — a deliberate exercise of the "absence is information" boundary (P3).


def _per_frame_value(key: str, n: int) -> Any:
    return {
        "time": 2.5,
        "masses": [1.0] * n,
        "velocities": [[0.0, 0.0, 0.0] for _ in range(n)],
        "forces": [[0.1, 0.0, 0.0] for _ in range(n)],
        "constraints": [],  # explicit "unconstrained" — present, not absent (§3.6).
        "total_energy": -3.0,
        "stress": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        "charges": [0.0] * n,
        "magnetic_moments": [0.0] * n,
        "total_spin": 0.0,
    }[key]


# canonical path -> (container key under a frame, field key). ``None`` container == the field lives
# directly on the frame (frame.time). Schema-declaration order (§3.5 → §3.3 → §3.6 → §3.7).
_PER_FRAME: tuple[tuple[str, str | None, str], ...] = (
    ("frame.time", None, "time"),
    ("atoms.masses", "atoms", "masses"),
    ("dynamics.velocities", "dynamics", "velocities"),
    ("dynamics.forces", "dynamics", "forces"),
    ("dynamics.constraints", "dynamics", "constraints"),
    ("electronic.total_energy", "electronic", "total_energy"),
    ("electronic.stress", "electronic", "stress"),
    ("electronic.charges", "electronic", "charges"),
    ("electronic.magnetic_moments", "electronic", "magnetic_moments"),
    ("electronic.total_spin", "electronic", "total_spin"),
)

_POPULATED_CELL: dict[str, Any] = {
    "lattice_vectors": [[15.0, 0.0, 0.0], [0.0, 15.0, 0.0], [0.0, 0.0, 15.0]],
    "pbc": [True, True, True],
    "space_group": None,
}


def _get_per_frame(frame: dict[str, Any], container: str | None, field: str) -> Any:
    return frame[field] if container is None else frame[container][field]


def _set_per_frame(frame: dict[str, Any], container: str | None, field: str, value: Any) -> None:
    if container is None:
        frame[field] = value
    else:
        frame[container][field] = value


def _natoms(data: dict[str, Any]) -> int:
    return len(data["frames"][0]["atoms"]["symbols"])


def _present_in_all_frames(data: dict[str, Any], container: str | None, field: str) -> bool:
    return all(_get_per_frame(f, container, field) is not None for f in data["frames"])


def _mutants(format_id: str) -> Iterator[tuple[str, CanonicalObject]]:
    """Yield ``(label, object)`` mutants for one golden base, plus the unmutated base itself."""
    base = _base_dict(format_id)
    n = _natoms(base)
    n_frames = len(base["frames"])

    # The unmutated worked example — the baseline every mutation is measured against.
    yield "base", CanonicalObject.model_validate(copy.deepcopy(base))

    # --- Per-frame optional fields: null a present one, populate an absent one -------------------
    for path, container, field in _PER_FRAME:
        data = copy.deepcopy(base)
        if _present_in_all_frames(base, container, field):
            for frame in data["frames"]:
                _set_per_frame(frame, container, field, None)
            yield f"null[{path}]", CanonicalObject.model_validate(data)
        else:
            for frame in data["frames"]:
                _set_per_frame(frame, container, field, _per_frame_value(field, n))
            yield f"populate[{path}]", CanonicalObject.model_validate(data)

    # --- Simulation cell as a unit (§3.4) --------------------------------------------------------
    data = copy.deepcopy(base)
    if base["frames"][0].get("cell") is not None:
        for frame in data["frames"]:
            frame["cell"] = None
        yield "null[cell]", CanonicalObject.model_validate(data)
        # space_group is only meaningful when the cell is present; populate it in place.
        sg = copy.deepcopy(base)
        for frame in sg["frames"]:
            frame["cell"]["space_group"] = "P1"
        yield "populate[cell.space_group]", CanonicalObject.model_validate(sg)
    else:
        for frame in data["frames"]:
            frame["cell"] = copy.deepcopy(_POPULATED_CELL)
        yield "populate[cell]", CanonicalObject.model_validate(data)

    # --- Root optional fields (Trajectory / Simulation / UserMetadata categories) ----------------
    # trajectory.timestep: absent in every four-format golden -> populate.
    data = copy.deepcopy(base)
    if data.get("trajectory") is None:
        data["trajectory"] = {"timestep": 1.0}
        yield "populate[trajectory.timestep]", CanonicalObject.model_validate(data)

    # simulation.* — absent in every golden (simulation is None) -> populate one field each.
    sim_fields: tuple[tuple[str, Any], ...] = (("source_code", "VASP"), ("temperature", 300.0))
    for sim_field, sim_value in sim_fields:
        data = copy.deepcopy(base)
        data["simulation"] = {sim_field: sim_value}
        yield f"populate[simulation.{sim_field}]", CanonicalObject.model_validate(data)

    # user_metadata scalar containers.
    um_fields: tuple[tuple[str, Any], ...] = (("tags", ["md"]), ("annotations", {"note": "gen"}))
    for um_field, um_value in um_fields:
        data = copy.deepcopy(base)
        data.setdefault("user_metadata", {})[um_field] = um_value
        yield f"populate[user_metadata.{um_field}]", CanonicalObject.model_validate(data)

    # --- Dynamic custom_* containers: null each present per-key path, populate a global one -------
    um = base.get("user_metadata") or {}
    for container_key in ("custom_global", "custom_per_atom", "custom_per_frame"):
        for key in um.get(container_key) or {}:
            data = copy.deepcopy(base)
            del data["user_metadata"][container_key][key]
            yield (
                f"null[user_metadata.{container_key}['{key}']]",
                CanonicalObject.model_validate(data),
            )
    if not (um.get("custom_global") or {}):
        data = copy.deepcopy(base)
        data.setdefault("user_metadata", {}).setdefault("custom_global", {})["gkey"] = "gval"
        yield "populate[user_metadata.custom_global['gkey']]", CanonicalObject.model_validate(data)

    # --- Per-frame `mixed` configuration (only when the golden has >1 frame) ----------------------
    # A field present in some frames only classifies as `mixed`; the completeness invariant must
    # account for it in preserved ∪ removed exactly like a uniformly-present field (Part 2 §3.11).
    if n_frames >= 2:
        for path, container, field in (
            ("dynamics.forces", "dynamics", "forces"),
            ("electronic.total_energy", "electronic", "total_energy"),
        ):
            if not _present_in_all_frames(base, container, field):
                data = copy.deepcopy(base)
                _set_per_frame(data["frames"][0], container, field, _per_frame_value(field, n))
                yield f"mixed[{path}]", CanonicalObject.model_validate(data)


def source_formats() -> list[str]:
    """Golden-backed source formats, sorted for stable, deterministic test ids."""
    return sorted(_GOLDEN_JSON)


def mutant_cases() -> list[tuple[str, str, CanonicalObject]]:
    """Every ``(case_id, source_format, object)`` mutant across all golden bases (stage 1).

    ``case_id`` embeds the base format and the mutation label so a failing parametrized case names
    exactly which field-path mutation, on which worked example, tripped the property.
    """
    cases: list[tuple[str, str, CanonicalObject]] = []
    for fmt in source_formats():
        for label, obj in _mutants(fmt):
            cases.append((f"{fmt}:{label}", fmt, obj))
    return cases
