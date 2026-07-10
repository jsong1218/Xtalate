"""The Information Discovery Engine (MASTER_SPEC Part 3 §6.1).

Generic by construction: **sniff → parse → introspect → report**, with no per-format logic.
The winning parser produces the Canonical Object under the full absence convention, and the
report is derived from ``field_presence()`` — so *discovery is exactly as trustworthy as
parsing* (§6.1): there is no separate lightweight "peek" path that could disagree with a real
conversion. A file whose format cannot be determined, or that fails to parse, raises
``ParseError`` — the same error contract every parser obeys (§5), which the CLI maps to its
parse-error exit code.

Layering (Part 1 §5.1): ``discovery`` sits above ``capabilities``/``parsers``/``exporters``,
so it drives the registry and reads the Capability Matrix, but is itself consumed only by
``conversion`` and the CLI.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

from chembridge.capabilities import Registry
from chembridge.discovery.report import DiscoveryReport, FieldPresenceEntry
from chembridge.discovery.sniffer import Sniffer, SniffResult
from chembridge.schema import CanonicalObject
from chembridge.sdk import CapabilityLevel, ParseError, ParseIssue

# The canonical scientific leaf paths the Discovery Report is complete over (Part 3 §6.2, §6.3):
# Part 2 §3.3–§3.7 plus frame.time and trajectory.timestep, in the §6.3 worked-example order.
# `atoms.atomic_numbers` (a derived mirror of symbols) and the metadata containers are excluded —
# they are summarized in `structure`/`extras`, not enumerated as losable leaf fields.
_LEAF_PATHS: tuple[str, ...] = (
    "atoms.symbols",
    "atoms.positions",
    "atoms.masses",
    "frame.time",
    "cell.lattice_vectors",
    "cell.pbc",
    "cell.space_group",
    "trajectory.timestep",
    "dynamics.velocities",
    "dynamics.forces",
    "dynamics.constraints",
    "electronic.total_energy",
    "electronic.stress",
    "electronic.charges",
    "electronic.magnetic_moments",
    "electronic.total_spin",
)


class DiscoveryEngine:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._sniffer = Sniffer(registry)

    def discover(
        self, data: bytes, *, filename: str | None = None, format_override: str | None = None
    ) -> DiscoveryReport:
        """Inspect ``data`` and return its Discovery Report (Part 3 §6). ``format_override``
        forces a parser (the sniff-override of §6.1); otherwise the sniffer selects one, and an
        undetermined format raises ``ParseError`` (nothing can be inspected without a parser)."""
        sniff = self._sniffer.sniff(data, filename)
        format_id = format_override or sniff.format_id
        if format_id is None:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="UNKNOWN_FORMAT",
                        message=(
                            "no registered format matched with sufficient confidence "
                            f"(top score {sniff.confidence:.2f}); pass an explicit format to override"
                        ),
                    )
                ]
            )
        if format_id not in {p.format_id for p in self._registry.parsers()}:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="UNKNOWN_FORMAT",
                        message=f"no parser registered for format {format_id!r}",
                    )
                ]
            )

        result = self._registry.get_parser(format_id).parse(BytesIO(data), filename=filename)
        canonical = result.canonical

        return DiscoveryReport(
            file={
                "filename": filename,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            format=self._format_block(format_id, sniff, format_override),
            structure=_structure(canonical),
            fields=self._fields(canonical, format_id),
            extras=_extras(canonical),
            issues=list(result.issues),
            schema_version=canonical.schema_version,
        )

    def _format_block(
        self, format_id: str, sniff: SniffResult, override: str | None
    ) -> dict[str, object]:
        caps = self._registry.capability_matrix()
        try:
            format_name = caps.get(format_id, "read").format_name
        except KeyError:
            format_name = format_id
        # Confidence is the sniffer's own score for the *selected* format — one honest rule for
        # both paths: the winning score when the sniffer chose, or the overridden format's real
        # score when the caller forced one (never a fabricated 1.0; the override is recorded
        # separately). A forced format that sniffed poorly shows its poor score, by design.
        confidence = next((c.confidence for c in sniff.candidates if c.format_id == format_id), 0.0)
        # Evidence = every *other* scored candidate, so the reader sees the full ranking that led
        # to this pick — including the format the sniffer *would* have chosen when overridden
        # (P1: show the alternatives, never just the winner).
        evidence = [
            {"format_id": c.format_id, "confidence": c.confidence}
            for c in sniff.candidates
            if c.format_id != format_id
        ]
        return {
            "format_id": format_id,
            "format_name": format_name,
            "confidence": confidence,
            "overridden": override is not None,
            "ambiguous": sniff.ambiguous,
            "sniff_evidence": evidence,
        }

    def _fields(self, canonical: CanonicalObject, format_id: str) -> list[FieldPresenceEntry]:
        presence = canonical.field_presence()
        by_path = {e.path: e for e in presence.entries}
        caps = self._registry.capability_matrix()
        entries: list[FieldPresenceEntry] = []
        for path in _LEAF_PATHS:
            pres = by_path.get(path)
            status = pres.status if pres is not None else "absent"
            present_frames = pres.present_frames if pres is not None else None
            level = caps.field_capability(format_id, "read", path).level
            detail = _detail(canonical, path) if status != "absent" else None
            entries.append(
                FieldPresenceEntry(
                    path=path,
                    status=status,
                    present_frames=present_frames,
                    format_capability=level,
                    detail=detail,
                )
            )
        return entries


def _structure(obj: CanonicalObject) -> dict[str, object]:
    symbols = obj.frames[0].atoms.symbols if obj.frames else []
    # Constant atom count across frames (Part 2 §3.2 invariant), so a single integer suffices.
    species: list[str] = []
    for sym in symbols:
        if sym not in species:
            species.append(sym)  # first-occurrence order, matching the §6.3 example (["O", "H"]).
    return {"frame_count": obj.frame_count, "atom_count": len(symbols), "species": species}


def _extras(obj: CanonicalObject) -> list[str]:
    """Carried-through keys not part of the fixed leaf schema (Part 3 §6.2): the per-file
    ``custom_*`` namespaces and ``simulation.extra`` keys, reported at container granularity."""
    um = obj.user_metadata
    extras: list[str] = []
    for container, keys in (
        ("user_metadata.custom_global", um.custom_global),
        ("user_metadata.custom_per_atom", um.custom_per_atom),
        ("user_metadata.custom_per_frame", um.custom_per_frame),
    ):
        extras.extend(f"{container}['{key}']" for key in keys)
    if obj.simulation is not None and obj.simulation.extra:
        extras.extend(f"simulation.extra['{key}']" for key in obj.simulation.extra)
    return extras


def _detail(obj: CanonicalObject, path: str) -> str | None:
    """A short human-readable descriptor for a present field (Part 3 §6.3). Detail richness is a
    documented cut-line (IMPLEMENTATION_PLAN M6); the high-value cases are covered, others None."""
    frames = obj.frame_count
    atoms = len(obj.frames[0].atoms.symbols) if obj.frames else 0
    if path == "atoms.symbols":
        return ", ".join(obj.frames[0].atoms.symbols) if obj.frames else None
    if path == "atoms.positions":
        return f"{frames} frame(s) × {atoms} atoms, Cartesian (Å)"
    if path == "cell.lattice_vectors":
        return "3×3 lattice (Å)"
    if path in ("dynamics.velocities", "dynamics.forces"):
        return f"{frames} frame(s) × {atoms} atoms × 3"
    return None


# `CapabilityLevel` is re-exported for renderers that annotate the inventory by capability.
__all__ = ["DiscoveryEngine", "DiscoveryReport", "FieldPresenceEntry", "CapabilityLevel"]
