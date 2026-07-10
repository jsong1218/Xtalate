"""The Conversion Engine (MASTER_SPEC Part 4 §1–2).

Orchestrates a single conversion: pre-flight diff → (recovery, M5) → `write_plan` export →
Conversion Report, with the completeness invariant asserted at finalization (review §4.5).
It delegates every format decision to the parsers/exporters via their `capabilities()`
declarations — there is no per-(source, target) logic here (Part 3 §4.3, the O(n) design).

**`write_plan` discipline (Part 4 §1 rules 1–4).** The engine does not pass a side-channel
list to the exporter; it *materializes* the plan as a filtered Canonical Object — the
`canonical′` of the sequence diagram — in which every field the plan excludes is set to
`None`. Handed that object, an exporter honoring the absence convention (it "never fabricates
values for absent fields", rule 2) writes exactly the plan and nothing more. This makes the
plan structurally enforced rather than trusted, and makes `canonical′` the precise *expected
object* the Validation Engine will diff the re-parsed output against (Part 5 §1, M5).

**M4 scope.** Recovery is detected but not resolved (M5): a conversion needing an unresolved
scenario is *refused* — a completed outcome with `status="refused"`, not an error (Part 4 §4).
Validation is not yet invoked as the final step (M5). `strict`-mode loss gating (Part 4 §4)
is likewise M5; M4 records `mode` and runs the permissive path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from chembridge import __version__
from chembridge.capabilities import Registry
from chembridge.conversion.preflight import PreflightDiff, build_preflight
from chembridge.conversion.report import ConversionReport
from chembridge.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    ConversionRecord,
    Dynamics,
    Electronic,
    Frame,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)

_SIMULATION_FIELDS = (
    "source_code",
    "calculator",
    "xc_functional",
    "pseudopotentials",
    "thermostat",
    "md_ensemble",
    "temperature",
    "extra",
)
_DERIVED_PATHS = frozenset({"atoms.atomic_numbers"})


class CompletenessInvariantError(AssertionError):
    """The final/refused report failed the completeness invariant (Part 4 §2) — a source-present
    path unaccounted for (silent loss, P1) or a supplied path that was present on the source
    (silent fabrication, P4). Never legitimate: raised always, in dev and in production."""


@dataclass
class ConversionResult:
    """Everything a caller (CLI, API, validation) needs from one conversion."""

    report: ConversionReport
    output: bytes | None  # None iff refused.
    # The write_plan-filtered object handed to the exporter — the Validation Engine's expected
    # object (Part 5 §1). None iff refused.
    canonical_out: CanonicalObject | None


class ConversionEngine:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    def preflight(
        self,
        source: CanonicalObject,
        *,
        source_format_id: str,
        target_format_id: str,
        source_filename: str | None = None,
        source_sha256: str | None = None,
        target_filename: str | None = None,
        mode: str = "permissive",
    ) -> ConversionReport:
        """The draft Conversion Report shown before conversion runs (Part 3 §4.3)."""
        matrix = self._registry.capability_matrix()
        diff = build_preflight(source, matrix, target_format_id)
        status = "awaiting_recovery" if diff.unresolved else "completed"
        report = self._assemble(
            stage="preflight",
            status=status,
            mode=mode,
            source=source,
            source_format_id=source_format_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            target_format_id=target_format_id,
            target_filename=target_filename,
            diff=diff,
        )
        _assert_completeness(report, source)
        return report

    def convert(
        self,
        source: CanonicalObject,
        *,
        source_format_id: str,
        target_format_id: str,
        source_filename: str | None = None,
        source_sha256: str | None = None,
        target_filename: str | None = None,
        mode: str = "permissive",
    ) -> ConversionResult:
        """Run the conversion end to end and produce the final report (Part 4 §1)."""
        matrix = self._registry.capability_matrix()
        diff = build_preflight(source, matrix, target_format_id)

        if diff.unresolved:
            # No recovery in M4 → a structured refusal (a completed outcome, not an error).
            refusal: dict[str, Any] = {
                "code": "RECOVERY_REQUIRED",
                "message": "conversion needs recovery decisions that are not yet available; "
                "supply them once the Recovery Engine (M5) lands, or choose a target that does "
                "not require the missing fields",
                "unresolved_scenarios": [
                    {"scenario": s.scenario, "path": s.path, "detail": s.detail}
                    for s in diff.unresolved
                ],
            }
            report = self._assemble(
                stage="final",
                status="refused",
                mode=mode,
                source=source,
                source_format_id=source_format_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                target_format_id=target_format_id,
                target_filename=target_filename,
                diff=diff,
                refusal=refusal,
            )
            _assert_completeness(report, source)
            return ConversionResult(report=report, output=None, canonical_out=None)

        canonical_out = _apply_write_plan(source, diff.write_plan, target_format_id)
        buffer = BytesIO()
        self._registry.get_exporter(target_format_id).export(canonical_out, buffer)

        report = self._assemble(
            stage="final",
            status="completed",
            mode=mode,
            source=source,
            source_format_id=source_format_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            target_format_id=target_format_id,
            target_filename=target_filename,
            diff=diff,
        )
        _assert_completeness(report, source)
        return ConversionResult(
            report=report, output=buffer.getvalue(), canonical_out=canonical_out
        )

    def _assemble(
        self,
        *,
        stage: str,
        status: str,
        mode: str,
        source: CanonicalObject,
        source_format_id: str,
        source_filename: str | None,
        source_sha256: str | None,
        target_format_id: str,
        target_filename: str | None,
        diff: PreflightDiff,
        refusal: dict[str, Any] | None = None,
    ) -> ConversionReport:
        return ConversionReport(
            report_id=str(uuid.uuid4()),
            stage=stage,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            mode=mode,  # type: ignore[arg-type]
            created_at=_utc_now(),
            source={
                "format_id": source_format_id,
                "filename": source_filename,
                "sha256": source_sha256,
                "schema_version": source.schema_version,
            },
            target={"format_id": target_format_id, "filename": target_filename},
            preserved=list(diff.preserved),
            removed=list(diff.removed),
            supplied=[],  # Recovery is M5; nothing is fabricated in M4.
            assumptions=[],
            warnings=list(diff.warnings),
            refusal=refusal,
        )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_write_plan(
    source: CanonicalObject, plan: set[str], target_format_id: str
) -> CanonicalObject:
    """Materialize the write_plan as ``canonical′``: a copy of ``source`` with every field the
    plan excludes set to ``None`` (Part 4 §1). ``atoms.symbols``/``atoms.positions`` (and the
    derived ``atomic_numbers``) are always kept — every format writes them, and they are the
    universal ``required_fields``. A convert-operation record is appended to provenance (§3.9)."""
    frames = [_filter_frame(frame, plan) for frame in source.frames]

    trajectory = source.trajectory
    if trajectory is not None and "trajectory.timestep" not in plan:
        # Keep the container (it carries multi-frame semantics) but drop the value.
        trajectory = TrajectoryMetadata(timestep=None)

    simulation = None
    if source.simulation is not None:
        kept = {
            name: getattr(source.simulation, name)
            for name in _SIMULATION_FIELDS
            if f"simulation.{name}" in plan
        }
        simulation = SimulationMetadata(**kept) if kept else None

    um = source.user_metadata
    user_metadata = UserMetadata(
        tags=um.tags if "user_metadata.tags" in plan else [],
        annotations=um.annotations if "user_metadata.annotations" in plan else {},
        custom_global=um.custom_global if "user_metadata.custom_global" in plan else {},
        custom_per_atom=um.custom_per_atom if "user_metadata.custom_per_atom" in plan else {},
        custom_per_frame=um.custom_per_frame if "user_metadata.custom_per_frame" in plan else {},
    )

    provenance = source.provenance.model_copy(
        update={
            "history": [
                *source.provenance.history,
                ConversionRecord(
                    timestamp=_utc_now(),
                    operation="convert",
                    source_format=source.provenance.source_format,
                    target_format=target_format_id,
                    tool_version=__version__,
                    parser_version=None,
                    assumptions=[],
                ),
            ]
        }
    )

    return CanonicalObject(
        schema_version=source.schema_version,
        frames=frames,
        trajectory=trajectory,
        simulation=simulation,
        provenance=provenance,
        user_metadata=user_metadata,
    )


def _filter_frame(frame: Frame, plan: set[str]) -> Frame:
    atoms = AtomsBlock(
        symbols=list(frame.atoms.symbols),
        positions=frame.atoms.positions,
        masses=frame.atoms.masses if "atoms.masses" in plan else None,
    )

    cell = None
    if frame.cell is not None and "cell.lattice_vectors" in plan:
        cell = Cell(
            lattice_vectors=frame.cell.lattice_vectors,
            pbc=frame.cell.pbc,
            space_group=frame.cell.space_group if "cell.space_group" in plan else None,
        )

    dynamics = Dynamics(
        velocities=frame.dynamics.velocities if "dynamics.velocities" in plan else None,
        forces=frame.dynamics.forces if "dynamics.forces" in plan else None,
        constraints=frame.dynamics.constraints if "dynamics.constraints" in plan else None,
    )
    electronic = Electronic(
        total_energy=frame.electronic.total_energy if "electronic.total_energy" in plan else None,
        stress=frame.electronic.stress if "electronic.stress" in plan else None,
        charges=frame.electronic.charges if "electronic.charges" in plan else None,
        magnetic_moments=(
            frame.electronic.magnetic_moments if "electronic.magnetic_moments" in plan else None
        ),
        total_spin=frame.electronic.total_spin if "electronic.total_spin" in plan else None,
    )
    return Frame(
        index=frame.index,
        time=frame.time if "frame.time" in plan else None,
        atoms=atoms,
        cell=cell,
        dynamics=dynamics,
        electronic=electronic,
    )


def _assert_completeness(report: ConversionReport, source: CanonicalObject) -> None:
    """The completeness invariant (Part 4 §2), asserted at finalization (review §4.5).

    Every source-present/`mixed` path (bar the derived mirror) must appear in `preserved` ∪
    `removed`; every `supplied` path must be absent on the source and trace to an Assumption.
    A violation is silent loss (P1) or silent fabrication (P4) — the two defects this whole
    project exists to make impossible — so it raises unconditionally, never merely logs."""
    presence = source.field_presence()
    accounted = {e.path for e in report.preserved} | {e.path for e in report.removed}
    for entry in presence.entries:
        if entry.status in ("present", "mixed") and entry.path not in _DERIVED_PATHS:
            if entry.path not in accounted:
                raise CompletenessInvariantError(
                    f"source-present path {entry.path!r} is in neither preserved nor removed — "
                    "silent loss (P1)"
                )

    source_present = set(presence.present_paths())
    assumption_ids = {a.id for a in report.assumptions}
    for supplied in report.supplied:
        if supplied.path in source_present:
            raise CompletenessInvariantError(
                f"supplied path {supplied.path!r} was present on the source — silent "
                "fabrication (P4)"
            )
        if supplied.from_assumption not in assumption_ids:
            raise CompletenessInvariantError(
                f"supplied path {supplied.path!r} references unknown assumption "
                f"{supplied.from_assumption!r}"
            )
