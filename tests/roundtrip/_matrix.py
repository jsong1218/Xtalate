"""Registry-driven round-trip matrix machinery (MASTER_SPEC Part 8 §2; not a test module).

The M9 cut line: the comparable subspace of a round-trip is **computed from the Capability Matrix
at test time, never hand-listed per pair**. The matrix does double duty — it drives conversion
(Part 3 §4.3) *and* defines what round-trip equality means (Part 5 §5). So a new plugin format joins
the two/three-hop suites the moment it is registered, with zero suite edits (**P6**); the
`test_matrix_enumeration` guard proves exactly that.

Everything here is derived from a live :class:`Registry`:

* the **pairs** come from ``registry.parsers()`` × ``registry.exporters()`` (filtered to formats
  that have a committed golden *source* fixture);
* the **comparable subspace** comes from ``registry.capability_matrix()``.

``FIXED_PRESETS`` are the deterministic recovery choices that let any fabricative/selective gap the
four v0.1 formats can hit (any → POSCAR without a lattice; a trajectory → a single-structure target)
resolve through the real Recovery Engine, so the round-trips exercise Assumption recording end to
end (Part 8 §2.2).

**Accepted risk — two-hop self-consistency (mitigated, not eliminated).** Because the two-hop suite
derives its expected comparable subspace from the *same* Capability Matrix that drives the engine, a
capability that is *wrongly declared* (e.g. a field marked FULL that the exporter actually mangles)
is consistent on both sides of the assertion and passes here. The backstop is the three-hop suite
(``test_three_hop``), whose ``A → B → A`` return is diffed against a **golden-anchored** original
(external truth, independent of the matrix), so a mis-declared capability on a curated high-risk
pair surfaces there. The residual gap — a mis-declaration on a pair the three-hop set does not
cover — is knowingly accepted for v0.2; widening the golden-anchored pair set is the v0.3+ lever
(Part 8 §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xtalate.capabilities import CapabilityMatrix, Registry
from xtalate.schema.paths import CANONICAL_FIELD_PATHS, DERIVED_PATHS
from xtalate.sdk import CapabilityLevel

GOLDEN = Path(__file__).parent.parent / "golden"

# Golden *source* fixtures, keyed by format_id: the source file plus its hand-verified expected
# Canonical Object (the external-truth anchor of Part 8 §3). ``contcar`` is byte-compatible with
# POSCAR (Part 3 §6.1); its own golden case carries the velocity block POSCAR does not, so it enrols
# CONTCAR as a round-trip *source* — the one fixture that flows velocities through the whole matrix.
_GOLDEN_DIRS: dict[str, tuple[str, str]] = {
    "xyz": ("xyz/water-traj", "water_traj.xyz"),
    "poscar": ("poscar/nacl-primitive", "POSCAR"),
    "extxyz": ("extxyz/co-in-cell", "sample.extxyz"),
    "contcar": ("contcar/co-md-restart", "CONTCAR"),
    # M13: the NpT case enrols XDATCAR as a source, so the one fixture whose *cell* varies frame
    # to frame flows through the whole matrix — the counterpart to CONTCAR carrying velocities.
    "xdatcar": ("xdatcar/si-npt-variable-cell", "XDATCAR"),
    # M14: the rich CO trajectory enrols ase_traj as a source — the one fixture that flows
    # velocities + forces + a fixed_atoms constraint together through the whole matrix (P6).
    "ase_traj": ("ase_traj/co-relax-3frame", "relax.traj"),
}

# Capability paths that are never round-trip content: provenance records *how* a file was read
# (which a faithful re-export may legitimately change — mirrors ``_format_helpers``'s dump), and the
# derived-mirror paths (``atoms.atomic_numbers``) that no format stores and the completeness
# invariant excludes — sourced from ``schema.paths.DERIVED_PATHS`` so this stays in step with the
# engine's exclusion by construction.
_EXCLUDED_PREFIXES = ("provenance.",)
_LEAF_PATHS: frozenset[str] = frozenset(
    p
    for p in CANONICAL_FIELD_PATHS
    if not p.startswith(_EXCLUDED_PREFIXES) and p not in DERIVED_PATHS
)

#: Deterministic recovery choices covering every fabricative/selective gap the four formats reach.
#: The engine applies only the scenarios its pre-flight diff actually detects, so passing the whole
#: superset on every conversion is harmless (an unused preset is ignored) and keeps the suite from
#: hand-listing which pair needs which recovery (Part 8 §2.2).
FIXED_PRESETS: dict[str, dict[str, Any]] = {
    "missing_lattice": {"choice": "bounding_box", "parameters": {"padding_ang": 5.0}},
    "frame_selection": {"choice": "first", "parameters": {}},
    # M14: ase_traj's ``fixed_atoms`` kind (D58) is not in POSCAR/CONTCAR's representable set
    # (``selective_dynamics``), so an ase_traj → POSCAR hop reaches the constraint-representation
    # gap. ``project`` keeps the representable subset and records the rest — deterministic, and
    # ignored by any pair that never hits the scenario (Part 8 §2.2).
    "constraint_representation": {"choice": "project", "parameters": {}},
}


@dataclass(frozen=True)
class GoldenSource:
    """A golden source fixture: the raw bytes, the on-disk filename (needed so a re-parse reproduces
    the golden's provenance for the anchor check), and its expected-Canonical anchor text."""

    format_id: str
    filename: str
    source: bytes
    expected_json: str


def golden_source(format_id: str) -> GoldenSource:
    rel, filename = _GOLDEN_DIRS[format_id]
    directory = GOLDEN / rel
    return GoldenSource(
        format_id=format_id,
        filename=filename,
        source=(directory / filename).read_bytes(),
        expected_json=(directory / "expected.canonical.json").read_text(),
    )


def source_formats_with_golden() -> list[str]:
    """Read-side formats that have a committed golden source fixture, sorted for stable test ids."""
    return sorted(_GOLDEN_DIRS)


def writeable_targets(registry: Registry) -> list[str]:
    """Every format with a registered exporter (the round-trip *targets*), from the registry."""
    return sorted(e.format_id for e in registry.exporters())


def readable_sources(registry: Registry) -> list[str]:
    """Every format with a registered parser (the round-trip *sources*), from the registry."""
    return sorted(p.format_id for p in registry.parsers())


def two_hop_pairs(registry: Registry) -> list[tuple[str, str]]:
    """All ``(source, target)`` pairs for the two-hop suite: every golden-backed source against
    every write-capable target, excluding identity (that is the job of ``test_identity``). Purely a
    function of the registry — a new exporter grows this list automatically (**P6**)."""
    targets = writeable_targets(registry)
    return [
        (source, target)
        for source in source_formats_with_golden()
        for target in targets
        if source != target
    ]


def roundtrippable(matrix: CapabilityMatrix, source: str, target: str) -> set[str]:
    """The leaf paths that survive ``source → target`` fully and unconditionally: FULL on the
    source's read side, FULL on the target's write *and* read sides (Part 5 §5, "read ∩ write").

    FULL-only — a PARTIAL cell (a level the exporter can express only under conditions) is the
    indeterminate middle, deliberately excluded from the *must-be-equal* set. It is still exercised
    indirectly: a corrupted lattice makes fractional↔Cartesian positions (which *are* FULL) fail, so
    the coordinate round-trip is validated through the positions it governs."""
    out: set[str] = set()
    for path in _LEAF_PATHS:
        if (
            matrix.field_capability(source, "read", path).level is CapabilityLevel.FULL
            and matrix.field_capability(target, "write", path).level is CapabilityLevel.FULL
            and matrix.field_capability(target, "read", path).level is CapabilityLevel.FULL
        ):
            out.add(path)
    return out


def comparable_subspace(matrix: CapabilityMatrix, a: str, b: str) -> set[str]:
    """The symmetric ``A ↔ B`` round-trip equality set: paths that survive *both* legs of
    ``A → B → A`` fully (Part 8 §2.3). The intersection of the two directional
    :func:`roundtrippable` sets — i.e. FULL on read and write of *both* formats."""
    return roundtrippable(matrix, a, b) & roundtrippable(matrix, b, a)


def unexpressible_source_paths(
    matrix: CapabilityMatrix, present_paths: list[str], target: str
) -> set[str]:
    """Source-present leaf paths the ``target`` cannot express at all (write capability NONE) — the
    "fields outside the intersection asserted absent" of Part 8 §2.2. Used by the two-hop suite to
    check the pre-flight routed them to ``removed``, the matrix→absence linkage at test time."""
    return {
        path
        for path in present_paths
        if path in _LEAF_PATHS
        and matrix.field_capability(target, "write", path).level is CapabilityLevel.NONE
    }
