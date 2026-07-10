"""The Conversion Engine (MASTER_SPEC Part 4 §1–2).

Orchestrates a single conversion: pre-flight diff → Recovery Engine → `write_plan` export →
Conversion Report → Validation Engine, with the completeness invariant asserted at finalization
(review §4.5). It delegates every format decision to the parsers/exporters via their
`capabilities()` declarations — there is no per-(source, target) logic here (Part 3 §4.3, the
O(n) design) — and every *recovery* decision to the Recovery Engine (Part 4 §3), mapping that
engine's plain result types onto the report's `Assumption`/`SuppliedEntry`/`RemovedEntry`.

**`write_plan` discipline (Part 4 §1 rules 1–4).** The engine does not pass a side-channel
list to the exporter; it *materializes* the plan as a filtered Canonical Object — the
`canonical′` of the sequence diagram — in which every field the plan excludes is set to
`None`. Handed that object, an exporter honoring the absence convention (it "never fabricates
values for absent fields", rule 2) writes exactly the plan and nothing more. `canonical′` is the
precise *expected object* the Validation Engine diffs the re-parsed output against (Part 5 §1).

**Recovery and refusal (Part 4 §3–4).** A conversion whose pre-flight diff detects a scenario
(target-required field absent, or `frame_count > max_frames`) is routed through the Recovery
Engine with the caller's presets. If a needed choice is missing the conversion is *refused* — a
completed outcome with `status="refused"`, not an error. Strict mode additionally refuses on
unacknowledged bulk loss or parse warnings (Part 4 §4).

**Validation (Part 5).** Every completed conversion is validated as an unconditional final step;
the resulting `ValidationReport` rides on `ConversionResult.validation`. There is no switch to
skip it — an unvalidated conversion is exactly the artifact this project exists to abolish.
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
from chembridge.conversion.report import (
    Assumption,
    ConversionReport,
    RemovedEntry,
    SuppliedEntry,
)
from chembridge.recovery import RecoveryEngine
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
from chembridge.sdk import ParseIssue
from chembridge.validation import ToleranceProfile, ValidationEngine, ValidationReport

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
    # Exactly one ValidationReport per completed conversion (Part 5 §3); None iff refused (a
    # refused conversion produces no output file and therefore nothing to validate).
    validation: ValidationReport | None = None


class ConversionEngine:
    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._recovery = RecoveryEngine()
        self._validation = ValidationEngine(registry)

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
            preserved=diff.preserved,
            removed=diff.removed,
            warnings=diff.warnings,
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
        recovery_choices: dict[str, dict[str, Any]] | None = None,
        parse_issues: list[ParseIssue] | None = None,
        acknowledge_loss: bool = False,
        acknowledge_parse_warnings: bool = False,
        tolerance_profile: str = "default",
    ) -> ConversionResult:
        """Run the conversion end to end and produce the final report (Part 4 §1)."""
        recovery_choices = recovery_choices or {}
        parse_issues = parse_issues or []
        matrix = self._registry.capability_matrix()
        diff = build_preflight(source, matrix, target_format_id)

        # --- Recovery (Part 4 §3) --------------------------------------------------------
        recovered = source
        assumptions: list[Assumption] = []
        supplied: list[SuppliedEntry] = []
        recovery_removed: list[RemovedEntry] = []
        write_plan = set(diff.write_plan)

        if diff.unresolved:
            outcome = self._recovery.resolve(source, diff.unresolved, recovery_choices)
            if outcome.canonical is None:
                return self._refuse(
                    source=source,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    refusal={
                        "code": "RECOVERY_REQUIRED",
                        "message": "conversion needs recovery decisions that were not supplied; "
                        "provide them as recovery_choices presets, or choose a target that does "
                        "not require the missing fields",
                        "unresolved_scenarios": [
                            {"scenario": s.scenario, "path": s.path, "detail": s.detail}
                            for s in outcome.unresolved
                        ],
                    },
                )
            recovered = outcome.canonical
            for applied in outcome.assumptions:
                assumptions.append(
                    Assumption(
                        id=applied.id,
                        scenario=applied.scenario,
                        choice=applied.choice,
                        parameters=applied.parameters,
                        origin=applied.origin,  # type: ignore[arg-type]
                        description=applied.description,
                    )
                )
                for sup in applied.supplied:
                    supplied.append(
                        SuppliedEntry(path=sup.path, from_assumption=applied.id, detail=sup.detail)
                    )
                    write_plan.add(sup.path)  # a fabricated field must be in the write_plan.
                for drop in applied.removed:
                    recovery_removed.append(
                        RemovedEntry(path=drop.path, reason=drop.reason, detail=drop.detail)
                    )

        removed = [*diff.removed, *recovery_removed]

        # --- Strict-mode gating (Part 4 §4) ----------------------------------------------
        if mode == "strict":
            if removed and not acknowledge_loss:
                return self._refuse(
                    source=source,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    removed=removed,
                    supplied=supplied,
                    assumptions=assumptions,
                    refusal={
                        "code": "UNACKNOWLEDGED_LOSS",
                        "message": "strict mode: reductive loss must be acknowledged "
                        "(acknowledge_loss=True) before this conversion will proceed",
                        "unresolved_scenarios": [],
                    },
                )
            parse_warnings = [i for i in parse_issues if i.severity == "warning"]
            if parse_warnings and not acknowledge_parse_warnings:
                return self._refuse(
                    source=source,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    removed=removed,
                    supplied=supplied,
                    assumptions=assumptions,
                    refusal={
                        "code": "UNACKNOWLEDGED_PARSE_WARNINGS",
                        "message": "strict mode: parse warnings must be acknowledged "
                        "(acknowledge_parse_warnings=True) before this conversion will proceed",
                        "unresolved_scenarios": [],
                    },
                )

        # --- Export (Part 4 §1) ----------------------------------------------------------
        recovered = _append_recovery_records(
            recovered, assumptions, source_format_id, target_format_id
        )
        canonical_out = _apply_write_plan(recovered, write_plan, target_format_id)
        exporter = self._registry.get_exporter(target_format_id)
        buffer = BytesIO()
        exporter.export(canonical_out, buffer)
        output = buffer.getvalue()

        # Warnings echo parse warnings (Part 3 §5 rule 5) alongside capability caveats (already in
        # diff.warnings). Export-time transformation warnings would be added here if the exporter
        # changed representation; the v0.1 POSCAR exporter writes canonical Cartesian unchanged.
        warnings = [*diff.warnings, *_parse_warnings(parse_issues)]

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
            preserved=diff.preserved,
            removed=removed,
            supplied=supplied,
            assumptions=assumptions,
            warnings=warnings,
        )
        _assert_completeness(report, source)

        # --- Validation (Part 5) — the unconditional final step --------------------------
        validation = self._validation.validate(
            expected=canonical_out,
            output=output,
            target_format_id=target_format_id,
            conversion_report=report,
            tolerance=ToleranceProfile.named(tolerance_profile),
        )
        return ConversionResult(
            report=report, output=output, canonical_out=canonical_out, validation=validation
        )

    def _refuse(
        self,
        *,
        source: CanonicalObject,
        source_format_id: str,
        source_filename: str | None,
        source_sha256: str | None,
        target_format_id: str,
        target_filename: str | None,
        mode: str,
        diff: PreflightDiff,
        refusal: dict[str, Any],
        removed: list[RemovedEntry] | None = None,
        supplied: list[SuppliedEntry] | None = None,
        assumptions: list[Assumption] | None = None,
    ) -> ConversionResult:
        """Assemble a refused Conversion Report (a completed outcome, not an error; Part 4 §4).

        The full pre-flight `preserved`/`removed` prediction rides along so a pipeline has
        everything it needs to decide whether to supply presets and retry."""
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
            preserved=diff.preserved,
            removed=removed if removed is not None else diff.removed,
            supplied=supplied or [],
            assumptions=assumptions or [],
            warnings=diff.warnings,
            refusal=refusal,
        )
        _assert_completeness(report, source)
        return ConversionResult(report=report, output=None, canonical_out=None, validation=None)

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
        preserved: list[Any],
        removed: list[Any],
        warnings: list[Any],
        supplied: list[SuppliedEntry] | None = None,
        assumptions: list[Assumption] | None = None,
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
            preserved=list(preserved),
            removed=list(removed),
            supplied=list(supplied or []),
            assumptions=list(assumptions or []),
            warnings=list(warnings),
            refusal=refusal,
        )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_warnings(issues: list[ParseIssue]) -> list[Any]:
    from chembridge.conversion.report import ReportWarning

    return [
        ReportWarning(code=i.code, message=i.message, source="parse")
        for i in issues
        if i.severity == "warning"
    ]


def _append_recovery_records(
    canonical: CanonicalObject,
    assumptions: list[Assumption],
    source_format_id: str,
    target_format_id: str,
) -> CanonicalObject:
    """Append one ``ConversionRecord(operation="recovery")`` per applied Assumption (Part 4 §3.2;
    §2 provenance mirroring), so the object stays independently self-explanatory."""
    if not assumptions:
        return canonical
    records = [
        ConversionRecord(
            timestamp=_utc_now(),
            operation="recovery",
            source_format=source_format_id,
            target_format=target_format_id,
            tool_version=__version__,
            parser_version=None,
            assumptions=[a.id],
        )
        for a in assumptions
    ]
    return canonical.model_copy(
        update={
            "provenance": canonical.provenance.model_copy(
                update={"history": [*canonical.provenance.history, *records]}
            )
        }
    )


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
