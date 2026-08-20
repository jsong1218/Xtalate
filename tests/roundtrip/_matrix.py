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
from xtalate.registry import default_registry
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
    # M44: the two parser-only VASP-output formats enrol as *sources* — a parser + golden but no
    # exporter, so the D159 seam keeps them out of the target axis automatically. Their fixtures are
    # label-complete (energy + forces + first-class stress), so every hop out of them exercises the
    # MLIP label triple through the matrix; the not-a-target guard (test_matrix_enumeration) pins
    # that neither ever appears as a conversion target.
    "vasprun": ("vasprun/relax-h2o", "vasprun.xml"),
    "outcar": ("outcar/relax-h2o", "OUTCAR"),
    # M19: the P 1 hexagonal anchor enrols cif as a source — the one fixture whose *native*
    # coordinates are fractional against a non-orthogonal cell (gamma = 120), so every hop out of
    # it exercises the fractional→Cartesian boundary against a lattice where a sign or transpose
    # error cannot hide. It is also the only source carrying site occupancy, which is how the
    # partial-occupancy pre-flight warning (M19 slice 2) gets exercised across the whole matrix.
    "cif": ("cif/zno-hexagonal-p1", "zno_hexagonal.cif"),
    # M47: the LAMMPS dump exporter closes M46's staging state, so lammps_dump enrols as a full
    # source *and* target (unlike the D159 VASP-output seam above). The element-labeled metal case
    # anchors it: declared metal units + an orthogonal box + velocities + a per-atom c_pe column
    # over two frames, so every hop out of it exercises the units carry and the custom-column loss
    # accounting. Its one recovery need on the way *in* to dump is write-side ``ambiguous_units``
    # (FIXED_PRESETS below); the coordinate family and image flags round-trip without a preset.
    "lammps_dump": ("lammps_dump/metal-ortho-declared", "dump.lammpstrj"),
    # M36: exfmt, the *installed reference plugin* (plugins/example-format/), enrolled as a source
    # so the compatibility canary participates in the full matrix — the milestone's "appears in the
    # nightly matrix with zero core changes" (Part 8 §2). Its parser lives in a separate
    # distribution, so unlike every entry above this one is only *live* when the plugin is
    # installed; ``source_formats_with_golden`` gates it on registration accordingly. The anchor
    # (a byte-exact mirror of the plugin's golden) sits under tests/golden/ because the plugin's own
    # fixtures are not shipped in its wheel and the matrix runs from the checkout, not the install.
    "exfmt": ("exfmt/water-monomer", "water_monomer.exfmt"),
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
    # M47: writing *to* lammps_dump without a resolved unit style refuses (write-side
    # ``ambiguous_units``, target-driven — D177). Every ``* → lammps_dump`` hop reaches it, so the
    # matrix pins a deterministic style; ``metal`` matches the golden source's own declared units,
    # keeping a lammps_dump → lammps_dump hop an honest identity rather than a unit re-label.
    "ambiguous_units": {"choice": "metal", "parameters": {}},
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
    """Read-side formats that have a committed golden source fixture *and* a registered parser to
    read it — sorted for stable test ids.

    A golden fixture is only usable as a round-trip *source* if some parser is registered to parse
    it, so this intersects the on-disk anchors with the default registry's parsers — the symmetric
    complement of the already-registry-derived *targets* (:func:`writeable_targets`). For the seven
    built-in formats this changes nothing (their parsers are always registered), so every existing
    caller is unaffected. It matters only for a plugin-provided source like ``exfmt`` (M36): when
    the reference plugin is installed the format joins the matrix as a source; when it is not, the
    anchor silently drops out and a plain checkout stays green — no parser is ever looked up for a
    format that has none. The default registry is the right lens here because every real caller
    drives the matrix from it or a superset of it, so a source it yields is always parseable by the
    registry a pair is run against."""
    registered = {parser.format_id for parser in default_registry().parsers()}
    return sorted(fmt for fmt in _GOLDEN_DIRS if fmt in registered)


def writeable_targets(registry: Registry) -> list[str]:
    """Every format with a registered exporter (the round-trip *targets*), from the registry."""
    return sorted(e.format_id for e in registry.exporters())


def readable_sources(registry: Registry) -> list[str]:
    """Every format with a registered parser (the round-trip *sources*), from the registry."""
    return sorted(p.format_id for p in registry.parsers())


def two_hop_pairs(registry: Registry) -> list[tuple[str, str]]:
    """All ``(source, target)`` pairs for the two-hop suite: every golden-backed source against
    every write-capable target, excluding identity (that is the job of ``test_identity``). Purely a
    function of the registry — a new exporter grows this list automatically (**P6**). This is the
    *full* nightly matrix; :func:`curated_pr_pairs` carves the fast PR subset from it."""
    targets = writeable_targets(registry)
    return [
        (source, target)
        for source in source_formats_with_golden()
        for target in targets
        if source != target
    ]


# High-risk unordered pairs curated for the PR gate (Part 8 §2.4): near-supersets (``xyz↔extxyz``),
# a fractional↔Cartesian coordinate transform (``poscar↔extxyz``), and a recovery-exercising
# trajectory→single-structure pair (``ase_traj→poscar``). Membership-guarded — a pair whose formats
# are not both available on the current branch (``ase_traj`` lands with the M14 ASE-trajectory
# format) drops out silently, so the list is correct everywhere and auto-completes as formats
# register (**P6**). The full matrix (nightly) is the superset; nothing here is a new pair.
#
# ``cif↔poscar`` joins in the post-v0.4 review. CIF was in neither curated set, so every CIF pair
# ran nightly-only and the newest, most structurally unusual format — the first fractional-native
# source, the first stating a cell as *parameters*, the only one with a canonical field NONE on
# write — had no golden-anchored coverage on the PR gate at all. That is the accepted risk in this
# module's own header, sitting on the format least able to afford it. POSCAR is the counterpart
# because ``cif↔poscar`` is the only CIF pair whose comparable subspace contains
# ``cell.lattice_vectors`` (extXYZ and ASE traj both declare the cell PARTIAL, which the FULL∩FULL
# rule excludes) — so it is the one that can witness a cell-parameter or angle error, and it
# reorders atoms on the POSCAR leg, exercising the ``atom_permutation`` seam from a fractional
# source. It also satisfies the existing coordinate-transform criterion more strongly than
# ``poscar↔extxyz`` does: fractional against a γ = 120° cell, where a sign or transpose error
# cannot hide behind an orthogonal lattice.
_HIGH_RISK_PAIRS: tuple[tuple[str, str], ...] = (
    ("xyz", "extxyz"),
    ("poscar", "extxyz"),
    ("ase_traj", "poscar"),
    ("cif", "poscar"),
)


def curated_pr_pairs(registry: Registry) -> list[tuple[str, str]]:
    """The curated two-hop subset the PR gate runs (Part 8 §2.4): each high-risk unordered pair
    expanded into every direction whose *source* has a committed golden fixture and whose *target*
    has a registered exporter. Membership-guarded against both the golden corpus and the registry,
    so an unregistered format (or one without a golden source) drops cleanly. A subset of
    :func:`two_hop_pairs` by construction — the remainder runs nightly."""
    sources = set(source_formats_with_golden())
    targets = set(writeable_targets(registry))
    out: set[tuple[str, str]] = set()
    for a, b in _HIGH_RISK_PAIRS:
        for source, target in ((a, b), (b, a)):
            if source != target and source in sources and target in targets:
                out.add((source, target))
    return sorted(out)


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
