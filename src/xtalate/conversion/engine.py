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

import re
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from xtalate import __version__
from xtalate._time import utc_now as _utc_now
from xtalate.capabilities import CapabilityMatrix, Registry
from xtalate.conversion.parse_recovery import ParseRecovery
from xtalate.conversion.preflight import (
    PreflightDiff,
    build_preflight,
    build_preflight_from_presence,
    on_demand_fabricative_scenarios,
    partial_occupancy_count,
)
from xtalate.conversion.report import (
    REPAIR_SCENARIO,
    Assumption,
    ConversionReport,
    PreservedEntry,
    RemovedEntry,
    ReportWarning,
    SuppliedEntry,
)
from xtalate.recovery import (
    AppliedAssumption,
    RecoveryEngine,
    UnresolvedScenario,
    available_options,
    frame_selection_stream_index,
    frame_selection_stream_records,
)
from xtalate.repair import (
    REPAIR_BLOCK_MISSING_LATTICE,
    AppliedRepair,
    RepairBlock,
    RepairError,
    RepairRequest,
    apply_repairs,
)
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    ConversionRecord,
    Dynamics,
    Electronic,
    Frame,
    PresenceAccumulator,
    PresenceMap,
    SimulationMetadata,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.schema.paths import DERIVED_PATHS as _DERIVED_PATHS
from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    FrameLimitExceeded,
    ParseError,
    ParseIssue,
    StreamFrame,
    StreamHeader,
    collapse_frame_issues,
)
from xtalate.validation import CheckResult, ToleranceProfile, ValidationEngine, ValidationReport

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


class CompletenessInvariantError(AssertionError):
    """The final/refused report failed the completeness invariant (Part 4 §2) — a source-present
    path unaccounted for (silent loss, P1) or a supplied path that was present on the source
    (silent fabrication, P4). Never legitimate: raised always, in dev and in production."""


@dataclass
class RecoveryPreview:
    """The Assumptions a convert with a given choice set *would* record — Part 6 §3.2 preview.

    Returned by :meth:`ConversionEngine.preview_recovery` so the Recovery Workflow UI can show a
    user the exact provenance they are about to create before they confirm it (P4). ``assumptions``
    are the report ``Assumption`` objects verbatim — same ``description`` text the final report will
    carry, because the preview runs the real recovery apply path. ``unresolved`` is non-empty when
    the choice set is incomplete: recovery is all-or-nothing, so a partial set produces *no*
    assumptions and instead names the scenarios still owed a decision (never a partial preview
    presented as complete)."""

    assumptions: list[Assumption]
    unresolved: list[UnresolvedScenario]


@dataclass
class ConversionResult:
    """Everything a caller (CLI, API, validation) needs from one conversion."""

    report: ConversionReport
    output: bytes | None  # None iff refused, or iff `outputs` carries a per-frame set (split_all).
    # The write_plan-filtered object handed to the exporter — the Validation Engine's expected
    # object (Part 5 §1). None iff refused.
    canonical_out: CanonicalObject | None
    # Exactly one ValidationReport per completed conversion (Part 5 §3); None iff refused (a
    # refused conversion produces no output file and therefore nothing to validate). For a
    # `split_all` conversion this is the merged report over all per-frame files.
    validation: ValidationReport | None = None
    # One output per frame, set *only* when `frame_selection=split_all` resolved (Part 4 §3.3): the
    # single-structure target receives one file per source frame. None for an ordinary single-file
    # conversion (where `output` carries the bytes). The CLI writes these into a directory.
    outputs: list[bytes] | None = None
    output_dir: dict[str, bytes] | None = None


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
        output_multifile: bool = True,
    ) -> ConversionReport:
        """The draft Conversion Report shown before conversion runs (Part 3 §4.3).

        ``output_multifile`` gates the ``split_all`` option the draft advertises (Part 4 §3.3):
        ``True`` for a directory-writing caller (CLI), ``False`` for the single-download HTTP
        service, so the pause the service shows never offers a choice it cannot fulfil."""
        matrix = self._registry.capability_matrix()
        diff = build_preflight(
            source,
            matrix,
            target_format_id,
            output_multifile=output_multifile,
            source_format_id=source_format_id,
        )
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
            # `pending` paths (a scenario decides their fate) ride in the draft as predicted-
            # preserved so the completeness invariant holds before any choice is made (Part 4 §3.3).
            preserved=[*diff.preserved, *diff.pending],
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
        recovery_origin: str = "preset",
        parse_issues: list[ParseIssue] | None = None,
        parse_recovery: ParseRecovery | None = None,
        acknowledge_loss: bool = False,
        acknowledge_parse_warnings: bool = False,
        tolerance_profile: str | ToleranceProfile = "default",
        output_multifile: bool = True,
        repairs: list[RepairRequest] | None = None,
    ) -> ConversionResult:
        """Run the conversion end to end and produce the final report (Part 4 §1).

        ``output_multifile`` gates the ``split_all`` recovery option (Part 4 §3.3). It defaults
        ``True`` (the CLI writes one file per frame into a directory). The HTTP service passes
        ``False``: it serves a single download, so ``split_all`` is neither offered nor accepted —
        a directly-supplied ``split_all`` choice fails the Recovery Engine's offered-set check and
        the conversion refuses, rather than completing with output the service would silently drop.

        ``parse_recovery`` carries any *parse-time* recovery (``missing_species``,
        ``truncate_corrupt_tail``) the caller already applied via ``parse_with_recovery`` — its
        Assumptions are merged ahead of pre-flight recovery and land in the report identically.

        ``recovery_origin`` labels the applied Assumptions' ``origin`` (Part 4 §2): ``"preset"`` for
        choices a caller supplied up front (the CLI, a pipeline), ``"user"`` for choices answered
        interactively through the ``awaiting_recovery`` pause (Part 6 §3.2, M23). It is a pure label
        on the record — it changes no recovery behaviour.

        ``repairs`` (v1.7 M64; D249/D250) is an ordered list of user-requested repair operations
        applied to the parsed object between parse and pre-flight — see the repair stage below. A
        ``None``/empty list runs exactly the pre-v1.7 pipeline (no repairs, byte-identical
        reports)."""
        recovery_choices = recovery_choices or {}
        parse_issues = list(parse_issues or [])
        if parse_recovery is not None:
            # The recovery's own warnings (POSCAR_SPECIES_SUPPLIED / XYZ_TRUNCATED) echo into the
            # report like any parse warning (Part 3 §5 rule 5), so the recovery is never silent.
            parse_issues = [*parse_issues, *parse_recovery.issues]
        matrix = self._registry.capability_matrix()
        # Parse-time recovery Assumptions (applied before the object existed) are merged ahead of
        # pre-flight recovery *and* repairs. Their fabricated paths are already present in `source`
        # (it is the recovered object), so they are excluded from the pre-flight `preserved` and
        # treated as absent-at-source by the completeness invariant — they belong in `supplied`
        # (Part 4 §3.3).
        parse_applied = list(parse_recovery.assumptions) if parse_recovery else []
        fabricated_at_parse = {sup.path for a in parse_applied for sup in a.supplied}

        # --- User-requested repair (v1.7 M64; D249/D250) ---------------------------------
        # Repairs run between parse and pre-flight: the requested operations are applied, in
        # user-specified order, to a copy of the parsed object, and every downstream stage — the
        # pre-flight diff, recovery, the Conversion Report, and the Validation Engine — sees the
        # *repaired* object. Application is all-or-nothing (the recovery-refusal precedent, D22):
        # one blocked operation refuses the whole conversion with nothing applied, and a block
        # that needs a recovery (a cell-less wrap → `missing_lattice`) refuses through that
        # existing scenario with its pair-specific options — repair fabricates nothing (D43). The
        # caller's `source` object is never mutated.
        repaired = source
        repair_applied: list[AppliedRepair] = []
        if repairs is not None:
            repair_outcome = apply_repairs(source, repairs)
            if repair_outcome.canonical is None:
                assert repair_outcome.blocked, "a refused repair outcome always names its blocker"
                blocked = repair_outcome.blocked[0]
                diff = build_preflight(
                    source,
                    matrix,
                    target_format_id,
                    output_multifile=output_multifile,
                    source_format_id=source_format_id,
                )
                # A repair-refused conversion still carries any parse-time recovery's
                # Assumptions/supplied so the refused report is complete (Part 4 §2, §3.3).
                for n, applied in enumerate(parse_applied, 1):
                    applied.id = f"A{n}"
                r_assumptions, r_supplied, r_preserved, r_removed, _ = _map_assumptions(
                    parse_applied
                )
                preflight_preserved = [
                    e for e in diff.preserved if e.path not in fabricated_at_parse
                ]
                blocked_scenarios = _repair_block_scenarios(
                    repair_outcome.blocked, matrix, target_format_id, output_multifile
                )
                return self._refuse(
                    source=source,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    preserved=[*preflight_preserved, *diff.pending, *r_preserved],
                    removed=[*diff.removed, *r_removed],
                    supplied=r_supplied,
                    assumptions=r_assumptions,
                    fabricated_at_parse=fabricated_at_parse,
                    refusal={
                        "code": "RECOVERY_REQUIRED",
                        "message": (
                            f"the requested repair {blocked.operation!r} cannot run: "
                            f"{blocked.detail}"
                        ),
                        "unresolved_scenarios": [
                            {
                                "scenario": s.scenario,
                                "path": s.path,
                                "detail": s.detail,
                                "options": s.options,
                            }
                            for s in blocked_scenarios
                        ],
                    },
                )
            repaired = repair_outcome.canonical
            repair_applied = repair_outcome.applied

        diff = build_preflight(
            repaired,
            matrix,
            target_format_id,
            output_multifile=output_multifile,
            source_format_id=source_format_id,
        )
        # Opt-in fabricative scenarios (velocity/mass emission) the user requested via
        # `recovery_choices` — not auto-detected by the diff, since the target does not *require*
        # these fields (Part 4 §3.3, D46). Merged with the diff's scenarios before recovery.
        on_demand = on_demand_fabricative_scenarios(
            repaired, matrix, target_format_id, recovery_choices, mode=mode
        )
        all_scenarios = [*diff.unresolved, *on_demand]

        # --- Pre-flight recovery (Part 4 §3) ---------------------------------------------
        recovered = repaired
        recovery_applied: list[AppliedAssumption] = []
        if all_scenarios:
            outcome = self._recovery.resolve(
                repaired, all_scenarios, recovery_choices, origin=recovery_origin
            )
            if outcome.canonical is None:
                # Refusal after a successful parse-time recovery *and/or* repair still carries
                # those applied records' Assumptions so the refused report is complete (Part 4
                # §2, §3.3).
                for n, applied in enumerate(parse_applied, 1):
                    applied.id = f"A{n}"
                for k, repair in enumerate(repair_applied, 1):
                    repair.id = f"A{len(parse_applied) + k}"
                r_assumptions, r_supplied, r_preserved, r_removed, _ = _map_assumptions(
                    parse_applied
                )
                preflight_preserved = [
                    e for e in diff.preserved if e.path not in fabricated_at_parse
                ]
                return self._refuse(
                    source=repaired,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    # A scenario-refused conversion still accounts for the `pending` paths (whose
                    # fate the unmade choice would decide) as predicted-preserved, so the refusal
                    # report satisfies the completeness invariant (Part 4 §2, §3.3).
                    preserved=[*preflight_preserved, *diff.pending, *r_preserved],
                    removed=[*diff.removed, *r_removed],
                    supplied=r_supplied,
                    assumptions=[*r_assumptions, *_repair_rows(repair_applied)],
                    warnings=[*_repair_warnings(repair_applied), *diff.warnings],
                    fabricated_at_parse=fabricated_at_parse,
                    refusal={
                        "code": "RECOVERY_REQUIRED",
                        "message": "conversion needs recovery decisions that were not supplied; "
                        "provide them as recovery_choices presets, or choose a target that does "
                        "not require the missing fields",
                        "unresolved_scenarios": [
                            {
                                "scenario": s.scenario,
                                "path": s.path,
                                "detail": s.detail,
                                "options": s.options,
                            }
                            for s in outcome.unresolved
                        ],
                    },
                )
            recovered = outcome.canonical
            recovery_applied = outcome.assumptions

        # Merge parse-time (first), user-requested repair, and pre-flight recovery Assumptions,
        # renumbering A1.. in application order (Part 4 §5 numbering): parse-time recovery
        # (during parse) → repairs (between parse and pre-flight) → pre-flight recovery. The
        # repairs' rows stay in the report's `assumptions` (scenario="repair"), so the report's
        # numbering *is* the recorded order (D250); their provenance records reference the same
        # ids.
        for n, applied in enumerate(parse_applied, 1):
            applied.id = f"A{n}"
        for k, repair in enumerate(repair_applied, 1):
            repair.id = f"A{len(parse_applied) + k}"
        for n, applied in enumerate(recovery_applied, len(parse_applied) + len(repair_applied) + 1):
            applied.id = f"A{n}"
        all_applied = [*parse_applied, *recovery_applied]
        assumptions, supplied, recovery_preserved, recovery_removed, plan_additions = (
            _map_assumptions(all_applied)
        )
        # The report's assumptions list reads in application order: the parse-time rows (A1..),
        # then the repair rows (their own user-requested section — `ConversionReport.repairs`),
        # then the pre-flight recovery rows.
        n_parse = len(parse_applied)
        assumptions = [
            *assumptions[:n_parse],
            *_repair_rows(repair_applied),
            *assumptions[n_parse:],
        ]
        repair_warnings = _repair_warnings(repair_applied)
        write_plan = set(diff.write_plan) | plan_additions

        preflight_preserved = [e for e in diff.preserved if e.path not in fabricated_at_parse]
        # A path the pre-flight optimistically predicted `preserved` but that recovery then
        # *fabricated* (`supplied`) was not, in fact, carried from the source. The case is a `mixed`
        # cell whose only cell-bearing frame `frame_selection` drops: pre-flight, seeing the cell
        # present in *some* frame, optimistically predicts `cell.lattice_vectors` preserved, but the
        # retained frame is cell-less and `missing_lattice` fills it (D51). So a supplied path is
        # struck from the pre-flight *prediction*; it stays in `removed` (the dropped original) and
        # `supplied` (the fabricated replacement), the honest removed+supplied pair D51 promises.
        #
        # The strike applies to the prediction only, never to `recovery_preserved` (M13): those
        # entries are the Recovery Engine's *record of what it actually did*, not a forecast. When a
        # `mixed` cell reaches a multi-frame lattice-requiring target (XDATCAR), `missing_lattice`
        # both carries the genuine lattices and fabricates the missing ones, and says so with a
        # PreservedField *and* a SuppliedField for the one path. Striking that would re-hide the
        # half of the truth the record exists to state.
        _supplied_paths = {s.path for s in supplied}
        preserved = [
            *[e for e in preflight_preserved if e.path not in _supplied_paths],
            *recovery_preserved,
        ]
        # A per-frame path a capability-NONE target already routes to `diff.removed` can *also* be
        # reported lost by `frame_selection` when it lived only in dropped frames — one removal, two
        # detectors. Dedupe by path (the capability diff's entry wins, as the more fundamental
        # reason) so the report never lists the same path removed twice.
        removed = _dedupe_removed([*diff.removed, *recovery_removed])

        # --- Strict-mode gating (Part 4 §4) ----------------------------------------------
        if mode == "strict":
            if removed and not acknowledge_loss:
                return self._refuse(
                    source=repaired,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    preserved=preserved,
                    removed=removed,
                    supplied=supplied,
                    assumptions=assumptions,
                    warnings=[*repair_warnings, *diff.warnings],
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
                    source=repaired,
                    source_format_id=source_format_id,
                    source_filename=source_filename,
                    source_sha256=source_sha256,
                    target_format_id=target_format_id,
                    target_filename=target_filename,
                    mode=mode,
                    diff=diff,
                    preserved=preserved,
                    removed=removed,
                    supplied=supplied,
                    assumptions=assumptions,
                    warnings=[*repair_warnings, *diff.warnings],
                    refusal={
                        "code": "UNACKNOWLEDGED_PARSE_WARNINGS",
                        "message": "strict mode: parse warnings must be acknowledged "
                        "(acknowledge_parse_warnings=True) before this conversion will proceed",
                        "unresolved_scenarios": [],
                    },
                )

        # --- Export (Part 4 §1) ----------------------------------------------------------
        # Provenance records ship per applied record, in report order: each repair row appends a
        # `ConversionRecord(operation="repair")` (the D249 triple (c), activating the reserved
        # value) and every recovery row appends `operation="recovery"` as before — a no-repair
        # conversion is byte-identical to the pre-v1.7 path.
        recovered = _append_assumption_records(
            recovered,
            [a for a in assumptions if a.scenario != REPAIR_SCENARIO],
            operation="recovery",
            source_format_id=source_format_id,
            target_format_id=target_format_id,
        )
        recovered = _append_assumption_records(
            recovered,
            [a for a in assumptions if a.scenario == REPAIR_SCENARIO],
            operation="repair",
            source_format_id=source_format_id,
            target_format_id=target_format_id,
        )
        canonical_out = _apply_write_plan(recovered, write_plan, target_format_id)
        exporter = self._registry.get_exporter(target_format_id)

        # A last value-level gate the capability diff cannot see: a field the target can hold in
        # general may still carry a value this format cannot state (a general-triclinic cell to a
        # LAMMPS dump, which holds only the restricted form). The exporter reports it via the
        # additive `unrepresentable` hook (D179); rather than crash mid-write or silently transform
        # (D43), the engine turns it into a clean refused report — a completed HTTP-200 outcome,
        # never an error (Part 4 §4; P1). Consulted on the write-plan-filtered object, after
        # recovery, so the refused report carries the recovery-augmented preserved/removed.
        unrepresentable = exporter.unrepresentable(canonical_out)
        if unrepresentable is not None:
            return self._refuse(
                source=repaired,
                source_format_id=source_format_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                target_format_id=target_format_id,
                target_filename=target_filename,
                mode=mode,
                diff=diff,
                preserved=preserved,
                removed=removed,
                supplied=supplied,
                assumptions=assumptions,
                warnings=[*repair_warnings, *diff.warnings],
                fabricated_at_parse=fabricated_at_parse,
                refusal={
                    "code": "UNREPRESENTABLE_VALUE",
                    "message": unrepresentable,
                    "unresolved_scenarios": [],
                },
            )

        # Warnings echo parse warnings (Part 3 §5 rule 5) alongside capability caveats (already in
        # diff.warnings). Export-time transformation warnings come from the exporter itself via the
        # additive `export_warnings` hook (Part 4 §1 rule 3, Part 2 §3.7.1; D151): the exporter owns
        # the representation changes it applies — e.g. extXYZ reversing a populated
        # `electronic.stress` to the compression-positive convention — and the engine reports them
        # with source="export". The v0.1 POSCAR exporter applies none, so this is usually empty.
        warnings = [
            # A repair's transformative-hazard statements (D251) lead: they are the one part of
            # the record the user's own request cannot be assumed to know (the R5 diffusion-path
            # loss), so they are never buried under format caveats.
            *repair_warnings,
            *diff.warnings,
            *[
                ReportWarning(code=w.code, message=w.message, source="export")
                for w in exporter.export_warnings(canonical_out)
            ],
            *_parse_warnings(parse_issues),
        ]

        report = self._assemble(
            stage="final",
            status="completed",
            mode=mode,
            source=repaired,
            source_format_id=source_format_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            target_format_id=target_format_id,
            target_filename=target_filename,
            preserved=preserved,
            removed=removed,
            supplied=supplied,
            assumptions=assumptions,
            warnings=warnings,
        )
        # Completeness is asserted over the object whose presence the diff accounted: the
        # *repaired* object (repair precedes pre-flight), never the pre-repair parse result — a
        # repair may change which paths pre-flight preserves/removes, and the invariant must
        # judge the report against what it actually describes (D250).
        _assert_completeness(report, repaired, fabricated_at_parse)

        # A caller may pass a named profile string (the common case) or a fully-built
        # ToleranceProfile — e.g. a custom table loaded from a file by the CLI (Part 5 §4.4).
        tolerance = (
            tolerance_profile
            if isinstance(tolerance_profile, ToleranceProfile)
            else ToleranceProfile.named(tolerance_profile)
        )

        # `frame_selection=split_all` (Part 4 §3.3): the single-structure target receives one file
        # per retained frame. Each file is exported and validated against its own single-frame
        # expected object; the per-file Validation Reports are merged into one (worst status wins).
        if _is_split_all(assumptions):
            outputs: list[bytes] = []
            validations: list[ValidationReport] = []
            for i in range(canonical_out.frame_count):
                single = canonical_out.single_frame(i)
                buffer = BytesIO()
                exporter.export(single, buffer)
                outputs.append(buffer.getvalue())
                validations.append(
                    self._validation.validate(
                        expected=single,
                        output=outputs[-1],
                        target_format_id=target_format_id,
                        conversion_report=report,
                        tolerance=tolerance,
                    )
                )
            return ConversionResult(
                report=report,
                output=None,
                canonical_out=canonical_out,
                validation=_merge_split_validations(validations),
                outputs=outputs,
            )

        if matrix.get(target_format_id, "write").directory_format:
            output_dir = dict(exporter.export_dir(canonical_out))
            validation = self._validation.validate_dir(
                expected=canonical_out,
                output=output_dir,
                target_format_id=target_format_id,
                conversion_report=report,
                tolerance=tolerance,
            )
            return ConversionResult(
                report=report,
                output=None,
                canonical_out=canonical_out,
                validation=validation,
                output_dir=output_dir,
            )

        buffer = BytesIO()
        exporter.export(canonical_out, buffer)
        output = buffer.getvalue()

        # --- Validation (Part 5) — the unconditional final step --------------------------
        validation = self._validation.validate(
            expected=canonical_out,
            output=output,
            target_format_id=target_format_id,
            conversion_report=report,
            tolerance=tolerance,
        )
        return ConversionResult(
            report=report, output=output, canonical_out=canonical_out, validation=validation
        )

    def preview_recovery(
        self,
        source: CanonicalObject,
        *,
        source_format_id: str,
        target_format_id: str,
        mode: str = "permissive",
        recovery_choices: dict[str, dict[str, Any]] | None = None,
        recovery_origin: str = "user",
        parse_recovery: ParseRecovery | None = None,
        output_multifile: bool = True,
    ) -> RecoveryPreview:
        """Preview the Assumptions a :meth:`convert` with ``recovery_choices`` would record, without
        exporting or validating (Part 6 §3.2; slice M31-S1).

        ``output_multifile`` must match the eventual :meth:`convert` call (the HTTP service passes
        ``False``) so the preview offers exactly the ``split_all``-gated option set the conversion
        will honour — a preview that advertised a choice the conversion then refused would mislead.

        This reproduces exactly the recovery *prefix* of :meth:`convert` — merge parse-time
        recovery, build the pre-flight diff, add on-demand fabricative scenarios, then run the
        Recovery Engine — and maps the result onto the report ``Assumption`` via the same
        ``_map_assumptions`` the final report uses. The ``description`` strings are therefore
        **byte-identical** to what the conversion will record (P4), which a client cannot reproduce
        without re-implementing the engine (P2). It stops before ``write_plan`` export and
        validation, so it is cheap enough to drive a live UI preview.

        Recovery is all-or-nothing: an incomplete choice set produces no assumptions and returns the
        still-unresolved scenarios instead (never a partial preview shown as complete). An *offered*
        choice with bad parameters, or an unoffered choice, raises the Recovery Engine's
        ``RecoveryError`` unchanged — the caller maps it to ``INVALID_RECOVERY_CHOICE`` exactly as
        the resume path does (Part 6 §6)."""
        recovery_choices = recovery_choices or {}
        matrix = self._registry.capability_matrix()
        diff = build_preflight(
            source,
            matrix,
            target_format_id,
            output_multifile=output_multifile,
            source_format_id=source_format_id,
        )
        on_demand = on_demand_fabricative_scenarios(
            source, matrix, target_format_id, recovery_choices, mode=mode
        )
        all_scenarios = [*diff.unresolved, *on_demand]

        parse_applied = list(parse_recovery.assumptions) if parse_recovery else []
        recovery_applied: list[AppliedAssumption] = []
        if all_scenarios:
            outcome = self._recovery.resolve(
                source, all_scenarios, recovery_choices, origin=recovery_origin
            )
            if outcome.canonical is None:
                return RecoveryPreview(assumptions=[], unresolved=list(outcome.unresolved))
            recovery_applied = outcome.assumptions

        # Same merge + A1.. numbering as `convert`, so a previewed assumption's identity matches the
        # one the final report records (Part 4 §5).
        all_applied = [*parse_applied, *recovery_applied]
        for n, applied in enumerate(all_applied, 1):
            applied.id = f"A{n}"
        assumptions, *_ = _map_assumptions(all_applied)
        return RecoveryPreview(assumptions=assumptions, unresolved=[])

    def streaming_eligible(self, source_format_id: str, target_format_id: str) -> bool:
        """Whether a ``(source, target)`` pair can take the streaming path (M12).

        Eligible iff both plugins stream **and** the target can never *require recovery*: no
        ``max_frames`` cap (would trigger ``frame_selection``), no recovery-able required field that
        could be absent (only the universally-present ``atoms.*`` are allowed), and no PARTIAL
        constraint capability (would trigger ``constraint_representation``). The exporter must also
        **preserve atom order** (it does not override ``atom_permutation``): streaming validation
        assumes an identity permutation map, so a reordering streaming target is excluded until one
        exists to thread a map. These are all static capability facts, decided before a byte is read
        — a conversion that *might* need a recovery choice mid-stream (which the streaming path does
        not yet resolve — M12 cut line) falls back to the materialized ``convert``. extXYZ→extXYZ,
        the trajectory pass-through, qualifies."""
        parser = self._registry.get_parser(source_format_id)
        exporter = self._registry.get_exporter(target_format_id)
        if not (parser.supports_streaming() and exporter.supports_streaming()):
            return False
        if type(exporter).atom_permutation is not ExporterPlugin.atom_permutation:
            return False  # a reordering exporter needs a permutation map streaming does not thread
        if type(exporter).unrepresentable is not ExporterPlugin.unrepresentable:
            # A value-level refusal (D179) the engine consults only on the materialized write
            # path (right after `_apply_write_plan`); the streaming path never asks, so an
            # exporter that can refuse a value must not take it — else the refusal is skipped
            # and unrepresentable bytes are written. Today `lammps_dump` is already excluded by
            # `requires_units_style` below; this guards any future streaming exporter that
            # overrides the hook without that capability.
            return False
        matrix = self._registry.capability_matrix()
        caps = matrix.get(target_format_id, "write")
        if caps.max_frames is not None:
            return False
        # A target whose write requires a declared unit style (M47-S1, D177) is a *static* fact
        # that needs a recovery choice — known before any frame is read, and no frame can
        # resolve it — so it can never take the recovery-free streaming path (reconciliation 3:
        # canonical → lammps_dump routes through materialized convert). The engine rejects
        # exactly this class by contract ("a static fact that could need a recovery choice
        # raises ValueError — use convert").
        if caps.requires_units_style:
            return False
        if any(r not in _UNIVERSAL_FIELDS for r in caps.required_fields):
            return False
        constraints = matrix.field_capability(target_format_id, "write", "dynamics.constraints")
        return constraints.level != CapabilityLevel.PARTIAL

    def frame_selection_streaming_eligible(
        self, source_format_id: str, target_format_id: str
    ) -> bool:
        """Whether a ``(source, target)`` pair can take the streaming *frame-selection* path (M13,
        D56): a multi-frame streaming source into a single-structure target, where the only recovery
        the conversion can need is ``frame_selection`` — resolved single-pass by capturing the one
        retained frame (``first``/``last``/``index``) while accumulating full presence.

        This is the pair ``streaming_eligible`` deliberately *excludes* (it bails on any
        ``max_frames`` cap). The distinction: ``convert_stream`` is recovery-free; ``convert_stream_
        select`` handles exactly one recovery — the frame reduction — because that recovery needs no
        data the single pass cannot capture. Only the **source** need stream: the memory win is in
        not holding the dropped frames, and the one retained frame is written through the exporter's
        ordinary whole-file ``export`` (a single structure), so a non-streaming single-structure
        exporter like POSCAR qualifies. The static gate is only: the source streams and the target
        caps frames at one. The two data-dependent exclusions — a source that carries *constraints*
        (which a PARTIAL target would route through ``constraint_representation``) and a retained
        frame that still needs a *fabricative* recovery (a ``mixed`` cell reduced to a cell-less
        frame → ``missing_lattice``) — are caught at runtime, where ``convert_stream_select`` hands
        them back to the materialized ``convert`` rather than mis-account or fabricate mid-stream.
        XDATCAR→POSCAR qualifies (XDATCAR carries neither constraints nor a missing lattice)."""
        parser = self._registry.get_parser(source_format_id)
        if not parser.supports_streaming():
            return False
        caps = self._registry.capability_matrix().get(target_format_id, "write")
        return caps.max_frames == 1

    def convert_stream(
        self,
        source_stream: Any,
        *,
        source_format_id: str,
        target_format_id: str,
        output: Any,
        source_filename: str | None = None,
        source_sha256: str | None = None,
        target_filename: str | None = None,
        mode: str = "permissive",
        tolerance_profile: str | ToleranceProfile = "default",
        acknowledge_loss: bool = False,
        validate: bool = True,
        max_frames: int | None = None,
    ) -> ConversionResult:
        """Stream a recovery-free conversion end to end with memory bounded by one frame (M12).

        A single pass over ``source_stream`` (an open binary stream) that (a) accumulates field
        presence, (b) applies the capability write plan to each frame and writes it straight to
        ``output`` through the streaming exporter, and (c) counts frames/constraints — so peak
        memory tracks the resident frame, never the trajectory length (Part 4 §6, P6). The
        Conversion Report is then built from the *accumulated* presence via the same
        ``build_preflight_from_presence`` the materialized path uses, and the completeness invariant
        (Part 4 §2) is asserted over that accumulated presence — so the streamed report is identical
        to what ``convert`` would produce (standing rule 3), proven by the report-equality tests.

        Only ``streaming_eligible`` pairs are accepted; a *static* fact that could need a recovery
        choice raises ``ValueError`` (use ``convert``), while a *data-dependent* one — M40-S2's
        ``ambiguous_stress_convention``, which fires on a source stress carry — is refused with a
        ``RECOVERY_REQUIRED`` report after the frames are streamed, exactly as the materialized
        path refuses the same input (standing rule 3). When ``validate`` is set and both the source
        and output streams are seekable, the conversion is validated **frame-pairwise over streams**
        (``validation.streaming``) — the expected side re-reads and filters the source on the fly,
        the actual side re-parses the output as a stream — so validation is memory-bounded too and
        the whole path stays sub-linear in frames (M12 deliverable 4).

        ``max_frames`` (optional, default ``None`` = current behaviour) makes the frame cap a real
        gate (M39-S3, F1): the streamed frame count is checked **as it streams**, and once it
        exceeds the cap the remaining frames are never read — :class:`FrameLimitExceeded` is raised
        mid-stream carrying the count-so-far and the cap, and the partial output is discarded like a
        mid-stream ``ParseError`` (``convert_stream`` returns no ConversionResult on failure). The
        CLI passes no cap (a local trajectory has none). The HTTP service enforces its
        ``settings.max_frames`` only through the materialized count-pass seams
        (``parse_with_recovery`` / ``DiscoveryEngine.discover``); ``convert_stream``'s own cap
        serves the CLI and the direct-SDK streaming path, which the service does not call.
        """
        if not self.streaming_eligible(source_format_id, target_format_id):
            raise ValueError(
                f"{source_format_id!r} → {target_format_id!r} is not streaming-eligible "
                "(a streaming plugin pair with a recovery-free target is required); use convert()"
            )
        parser = self._registry.get_parser(source_format_id)
        exporter = self._registry.get_exporter(target_format_id)
        matrix = self._registry.capability_matrix()
        caps = matrix.get(target_format_id, "write")
        write_plan = _capability_write_plan(caps)

        stream = parser.parse_stream(source_stream, filename=source_filename)
        header = stream.header
        # A custom container the target writes only *specific* keys of (D69 — extXYZ's
        # custom_per_atom name pattern, xdatcar's custom_global comment key) must enter the write
        # plan per-key, not as the whole container: a container-level entry makes `_kept_custom`
        # keep every key — including ones the pre-flight classifies Removed and the exporter drops
        # — so the streamed validation expected side would demand them back and false-fail where
        # the materialized path passes (standing rule 3). The keys are eager in the header (both
        # containers are object-level), so the refinement is known before the pass, exactly like the
        # capability plan itself. `custom_per_frame` is deliberately *not* refined here — and the
        # reason is the streaming-eligibility gate, not the absence of a per-key-classifying target
        # (lammps_dump does per-key-classify custom_per_frame and is a streaming exporter). It is
        # safe only because `streaming_eligible()` rejects every target that would need it:
        # lammps_dump is `requires_units_style` and so never streams, and no other
        # streaming-eligible exporter per-key-classifies custom_per_frame. If one ever does, this
        # loop cannot fix it — custom_per_frame keys are per-frame, not eager in the header, so the
        # refinement would have to live in `_filter_stream_frame` (per row), not here. Widen the
        # eligibility gate or add that per-frame refinement before relying on it.
        for container, keys in (
            ("user_metadata.custom_global", header.custom_global),
            ("user_metadata.custom_per_atom", header.custom_per_atom),
        ):
            allowed = caps.writable_custom_keys.get(container)
            pattern = caps.writable_custom_key_pattern.get(container)
            if allowed is None and pattern is None:
                continue
            write_plan.discard(container)
            for key in keys:
                is_writable = (
                    key in allowed
                    if allowed is not None
                    else re.fullmatch(pattern or "", key) is not None
                )
                if is_writable:
                    write_plan.add(f"{container}['{key}']")
        acc = PresenceAccumulator(header.schema_version)
        acc.observe_header(
            trajectory=header.trajectory,
            simulation=header.simulation,
            tags=header.tags,
            annotations=header.annotations,
            custom_global=header.custom_global,
            custom_per_atom=header.custom_per_atom,
        )
        counters = {"frames": 0}

        def _planned_frames() -> Any:
            for sf in stream.frames():
                present_keys = [k for k, v in sf.per_frame_custom.items() if v is not None]
                acc.observe_frame(sf.frame, present_keys)
                counters["frames"] += 1
                # The cap, counted as the frames stream: once the count exceeds max_frames the
                # remaining frames are never read (mid-stream, before materialization), and the
                # caller translates the exception (the service: 422 FRAME_LIMIT_EXCEEDED).
                if max_frames is not None and counters["frames"] > max_frames:
                    raise FrameLimitExceeded(frame_count=counters["frames"], max_frames=max_frames)
                yield _filter_stream_frame(sf, write_plan)

        # The exporter writes each planned frame as it is yielded — the single streamed pass. A
        # ``ParseError`` raised by the source mid-stream (frame k corrupt) propagates through here
        # (Part 3 §5): frames 0..k-1 may already be in ``output``, so that partial write is dropped
        # and the error re-raised — ``convert_stream`` returns *no* ConversionResult on failure, and
        # a half-written output can never masquerade as a completed conversion (M12 deliverable 5).
        # (The opt-in ``truncate_at_last_valid_frame`` *recovery* — keep the good prefix and proceed
        # — lands with M13's XDATCAR, the streaming format that raises that recoverable hint; extXYZ
        # streaming raises a non-recoverable error here.)
        filtered_header = _filter_stream_header(header, write_plan)
        try:
            exporter.export_stream(filtered_header, _planned_frames(), output)
        except (ParseError, FrameLimitExceeded):
            # A mid-stream ParseError (frame k corrupt) or a mid-stream FrameLimitExceeded (the
            # frame cap fired) leaves frames 0..k-1 already written: drop that partial write and
            # re-raise — convert_stream returns *no* ConversionResult on failure, and a half-
            # written output can never masquerade as a completed conversion (M12 deliverable 5).
            _discard_partial_output(output)
            raise

        presence = acc.result()
        diff = build_preflight_from_presence(
            presence,
            frame_count=counters["frames"],
            has_constraints=False,  # constraint targets are ineligible; no frame carries a subset
            # Occupancy is only ever produced by CIF, a single-structure format that never streams,
            # so a streamed source carries none — the same scalar (0) the materialized path would
            # compute for the same occupancy-free object (rule 3).
            partial_occupancy=partial_occupancy_count(None),
            matrix=matrix,
            target_format_id=target_format_id,
            source_format_id=source_format_id,
        )
        preserved = [*diff.preserved, *diff.pending]
        removed = diff.removed
        warnings = [*diff.warnings, *_parse_warnings(stream.issues)]

        if diff.unresolved:
            # M40-S2: a *data-dependent* recovery fired mid-stream. `streaming_eligible` rules out
            # every scenario the static capability facts can trigger, but
            # `ambiguous_stress_convention` fires on the data itself — a source stress carry **and**
            # a target that can express `electronic.stress` (extXYZ becomes such a target in
            # M40-S2). The streaming path cannot resolve a convention choice, so it must refuse
            # exactly as the materialized `convert` does (standing rule 3: streamed and materialized
            # reports never diverge) — a silent pass-through of an undeclared sign convention is
            # the exact hazard M40 exists to kill. The already-written frames are discarded like a
            # mid-stream error (M12 deliverable 5).
            _discard_partial_output(output)
            report = self._assemble(
                stage="final",
                status="refused",
                mode=mode,
                source_schema_version=presence.schema_version,
                source_format_id=source_format_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                target_format_id=target_format_id,
                target_filename=target_filename,
                preserved=preserved,
                removed=removed,
                warnings=diff.warnings,
                refusal={
                    "code": "RECOVERY_REQUIRED",
                    "message": "conversion needs recovery decisions that were not supplied; "
                    "provide them as recovery_choices presets (the materialized convert), or "
                    "choose a target that does not require the missing fields",
                    "unresolved_scenarios": [
                        {
                            "scenario": s.scenario,
                            "path": s.path,
                            "detail": s.detail,
                            "options": s.options,
                        }
                        for s in diff.unresolved
                    ],
                },
            )
            _assert_completeness_presence(report, presence)
            return ConversionResult(report=report, output=None, canonical_out=None, validation=None)

        if mode == "strict" and removed and not acknowledge_loss:
            report = self._assemble(
                stage="final",
                status="refused",
                mode=mode,
                source_schema_version=presence.schema_version,
                source_format_id=source_format_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                target_format_id=target_format_id,
                target_filename=target_filename,
                preserved=preserved,
                removed=removed,
                warnings=diff.warnings,
                refusal={
                    "code": "UNACKNOWLEDGED_LOSS",
                    "message": "strict mode: reductive loss must be acknowledged "
                    "(acknowledge_loss=True) before this conversion will proceed",
                    "unresolved_scenarios": [],
                },
            )
            _assert_completeness_presence(report, presence)
            return ConversionResult(report=report, output=None, canonical_out=None, validation=None)

        report = self._assemble(
            stage="final",
            status="completed",
            mode=mode,
            source_schema_version=presence.schema_version,
            source_format_id=source_format_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            target_format_id=target_format_id,
            target_filename=target_filename,
            preserved=preserved,
            removed=removed,
            warnings=warnings,
        )
        _assert_completeness_presence(report, presence)

        validation: ValidationReport | None = None
        if validate and _seekable(output) and _seekable(source_stream):
            tolerance = (
                tolerance_profile
                if isinstance(tolerance_profile, ToleranceProfile)
                else ToleranceProfile.named(tolerance_profile)
            )
            validation = self._validate_streamed(
                parser=parser,
                source_stream=source_stream,
                source_filename=source_filename,
                output=output,
                write_plan=write_plan,
                target_format_id=target_format_id,
                report=report,
                tolerance=tolerance,
                schema_version=presence.schema_version,
            )
        return ConversionResult(
            report=report, output=None, canonical_out=None, validation=validation
        )

    def convert_stream_select(
        self,
        source_stream: Any,
        *,
        source_format_id: str,
        target_format_id: str,
        output: Any,
        frame_selection: dict[str, Any],
        source_filename: str | None = None,
        source_sha256: str | None = None,
        target_filename: str | None = None,
        mode: str = "permissive",
        tolerance_profile: str | ToleranceProfile = "default",
        acknowledge_loss: bool = False,
        validate: bool = True,
    ) -> ConversionResult:
        """Stream a multi-frame source into a single-structure target under a ``frame_selection``
        reduction, holding one frame resident (M13; DECISIONS.md D56 — the recovery interplay M12
        deferred, whose worked case is XDATCAR→POSCAR).

        A single pass over ``source_stream`` accumulates full field presence (all frames) and counts
        frames while capturing *only* the one retained frame — ``first`` (frame 0), ``last`` (the
        running last), or ``index=k`` (frame k). After the pass the retained frame is materialized
        into a single-structure object (identical to ``source.single_frame(index)``) and exported
        and validated exactly as the materialized ``convert`` would — so peak memory tracks one
        frame, never the trajectory length, yet the Conversion Report and the output bytes are
        **byte-identical** to ``convert(source, recovery_choices={"frame_selection": ...})`` on the
        same file (standing rule 3). The frame_selection accounting itself is produced by the shared
        ``recovery.frame_selection_stream_records``, driven by the accumulated presence, so the
        dropped-frame ``removed`` entries match the materialized recovery to the byte.

        Only ``frame_selection_streaming_eligible`` pairs and the ``first``/``last``/``index``
        choices are accepted. ``split_all`` (one output file per frame) and any file whose retained
        frame would still need a *fabricative* recovery (a ``mixed`` cell reduced to a cell-less
        frame → ``missing_lattice``) are refused back to the materialized ``convert`` with a
        ``ValueError`` — the streaming path never fabricates mid-pass."""
        if not self.frame_selection_streaming_eligible(source_format_id, target_format_id):
            raise ValueError(
                f"{source_format_id!r} → {target_format_id!r} is not frame-selection-streaming-"
                "eligible (a streaming pair into a single-structure target is required); use "
                "convert()"
            )
        code = str(frame_selection.get("choice"))
        if code == "split_all":
            raise ValueError(
                "frame_selection=split_all fans one output into many files and is not a single-"
                "frame streaming case; use convert()"
            )
        parser = self._registry.get_parser(source_format_id)
        exporter = self._registry.get_exporter(target_format_id)
        matrix = self._registry.capability_matrix()

        # Capture strategy is fixed by the choice code (known now); `n` and the index a
        # `last`/`index` choice resolves to are known only after the single pass. Hold at most the
        # frame-0, running-last, and `index=k` candidates — three references, O(1) in frame count.
        want_index: int | None = None
        if code == "index":
            raw = (frame_selection.get("parameters", {}) or {}).get("frame_index")
            want_index = raw if isinstance(raw, int) and not isinstance(raw, bool) else None

        stream = parser.parse_stream(source_stream, filename=source_filename)
        header = stream.header
        acc = PresenceAccumulator(header.schema_version)
        acc.observe_header(
            trajectory=header.trajectory,
            simulation=header.simulation,
            tags=header.tags,
            annotations=header.annotations,
            custom_global=header.custom_global,
            custom_per_atom=header.custom_per_atom,
        )
        first_frame: StreamFrame | None = None
        last_frame: StreamFrame | None = None
        indexed_frame: StreamFrame | None = None
        n = 0
        for sf in stream.frames():
            present_keys = [k for k, v in sf.per_frame_custom.items() if v is not None]
            acc.observe_frame(sf.frame, present_keys)
            if n == 0:
                first_frame = sf
            last_frame = sf
            if want_index is not None and n == want_index:
                indexed_frame = sf
            n += 1
        presence = acc.result()

        # A source carrying constraints against a PARTIAL target would need
        # `constraint_representation` (a subset choice this path does not resolve), and
        # `has_constraints=False` below could not then be trusted — so refuse it back to the
        # materialized `convert`. XDATCAR never carries constraints, so this never fires for it.
        if presence.status_of("dynamics.constraints") != "absent":
            raise ValueError(
                f"{source_format_id!r} carries constraints, whose representation is a recovery "
                "this streaming path does not resolve; use convert()"
            )

        diff = build_preflight_from_presence(
            presence,
            frame_count=n,
            has_constraints=False,  # guaranteed by the constraint-absence guard just above
            # Occupancy is only ever produced by CIF, a single-structure format that never streams,
            # so a streamed source carries none (frame selection cannot introduce it either).
            partial_occupancy=partial_occupancy_count(None),
            matrix=matrix,
            target_format_id=target_format_id,
            source_format_id=source_format_id,
        )
        fs_scenario = next((s for s in diff.unresolved if s.scenario == "frame_selection"), None)
        other = [s for s in diff.unresolved if s.scenario != "frame_selection"]
        if other:
            # The retained frame still lacks a target-required field (e.g. a mixed cell reduced to
            # a cell-less frame → missing_lattice): fabricating mid-stream is out of this path's
            # scope, so hand it back to the materialized convert, which resolves it lazily (D56).
            raise ValueError(
                f"{source_format_id!r} → {target_format_id!r} on this input needs recovery beyond "
                f"frame_selection ({sorted(s.scenario for s in other)}); use convert()"
            )

        # Resolve the retained frame + its assumption. A source already single-structure (n ≤ 1)
        # trips no frame_selection scenario — no reduction, no assumption — matching materialized.
        if fs_scenario is None:
            index = 0
            selected = first_frame
        else:
            index = frame_selection_stream_index(frame_selection, n)  # validates; may RecoveryError
            selected = {"first": first_frame, "last": last_frame, "index": indexed_frame}[code]
        if selected is None:  # pragma: no cover - guarded by eligibility + a non-empty stream
            raise ValueError("no frame was captured for the requested selection")
        reduced = self._single_frame_object(header, selected)
        applied: list[AppliedAssumption] = []
        if fs_scenario is not None:
            applied.append(
                frame_selection_stream_records(
                    reduced,
                    presence,
                    frame_count=n,
                    index=index,
                    code=code,
                    origin="preset",
                )
            )

        assumptions, supplied, recovery_preserved, recovery_removed, plan_additions = (
            _map_assumptions(applied)
        )
        write_plan = set(diff.write_plan) | plan_additions
        _supplied_paths = {s.path for s in supplied}
        preserved = [
            *[e for e in diff.preserved if e.path not in _supplied_paths],
            *recovery_preserved,
        ]
        removed = _dedupe_removed([*diff.removed, *recovery_removed])
        warnings = [*diff.warnings, *_parse_warnings(stream.issues)]

        if mode == "strict" and removed and not acknowledge_loss:
            report = self._assemble(
                stage="final",
                status="refused",
                mode=mode,
                source_schema_version=presence.schema_version,
                source_format_id=source_format_id,
                source_filename=source_filename,
                source_sha256=source_sha256,
                target_format_id=target_format_id,
                target_filename=target_filename,
                preserved=preserved,
                removed=removed,
                supplied=supplied,
                assumptions=assumptions,
                warnings=diff.warnings,
                refusal={
                    "code": "UNACKNOWLEDGED_LOSS",
                    "message": "strict mode: reductive loss must be acknowledged "
                    "(acknowledge_loss=True) before this conversion will proceed",
                    "unresolved_scenarios": [],
                },
            )
            _assert_completeness_presence(report, presence)
            return ConversionResult(report=report, output=None, canonical_out=None, validation=None)

        report = self._assemble(
            stage="final",
            status="completed",
            mode=mode,
            source_schema_version=presence.schema_version,
            source_format_id=source_format_id,
            source_filename=source_filename,
            source_sha256=source_sha256,
            target_format_id=target_format_id,
            target_filename=target_filename,
            preserved=preserved,
            removed=removed,
            supplied=supplied,
            assumptions=assumptions,
            warnings=warnings,
        )
        _assert_completeness_presence(report, presence)

        recovered = _append_assumption_records(
            reduced,
            assumptions,
            operation="recovery",
            source_format_id=source_format_id,
            target_format_id=target_format_id,
        )
        canonical_out = _apply_write_plan(recovered, write_plan, target_format_id)
        buffer = BytesIO()
        exporter.export(canonical_out, buffer)
        output_bytes = buffer.getvalue()
        output.write(output_bytes)

        tolerance = (
            tolerance_profile
            if isinstance(tolerance_profile, ToleranceProfile)
            else ToleranceProfile.named(tolerance_profile)
        )
        validation: ValidationReport | None = None
        if validate:
            validation = self._validation.validate(
                expected=canonical_out,
                output=output_bytes,
                target_format_id=target_format_id,
                conversion_report=report,
                tolerance=tolerance,
            )
        return ConversionResult(
            report=report, output=output_bytes, canonical_out=canonical_out, validation=validation
        )

    @staticmethod
    def _single_frame_object(header: StreamHeader, sf: StreamFrame) -> CanonicalObject:
        """Materialize the one retained ``StreamFrame`` into a single-structure ``CanonicalObject``
        equal to ``full_source.single_frame(index)`` — the retained frame re-indexed to 0, the
        trajectory container dropped (a lone frame is a structure, not a trajectory), and its
        ``custom_per_frame`` sliced to the single row. Reuses the streaming ``materialize`` so the
        reconstruction rule lives in exactly one place (Part 2 §3.10)."""
        from xtalate.sdk.streaming import FrameStream, materialize

        reindexed = StreamFrame(
            frame=sf.frame.model_copy(update={"index": 0}),
            per_frame_custom=sf.per_frame_custom,
        )
        obj, _ = materialize(FrameStream(header, iter([reindexed])))
        return obj

    def _validate_streamed(
        self,
        *,
        parser: Any,
        source_stream: Any,
        source_filename: str | None,
        output: Any,
        write_plan: set[str],
        target_format_id: str,
        report: ConversionReport,
        tolerance: ToleranceProfile,
        schema_version: str,
    ) -> ValidationReport:
        """Validate a streamed conversion frame-pairwise (M12 deliverable 4), holding one frame pair
        resident. The *expected* side re-reads the source and filters each frame through the write
        plan on the fly (the ``canonical′`` reference of Part 5 §1, unmaterialized); the *actual*
        side re-parses the just-written output as a stream. Both are diffed by
        ``validation.streaming.validate_stream``, which produces the identical ``ValidationReport``
        the batch engine would (standing rule 3)."""
        from xtalate.sdk.streaming import FrameStream
        from xtalate.validation.streaming import validate_stream

        source_stream.seek(0)
        src_restream = parser.parse_stream(source_stream, filename=source_filename)
        expected_header = _filter_stream_header(src_restream.header, write_plan)

        def _expected_frames() -> Any:
            for sf in src_restream.frames():
                yield _filter_stream_frame(sf, write_plan)

        expected = FrameStream(expected_header, _expected_frames())
        output.seek(0)
        return validate_stream(
            self._registry,
            expected=expected,
            output_stream=output,
            target_format_id=target_format_id,
            conversion_report=report,
            tolerance=tolerance,
            expected_schema_version=schema_version,
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
        preserved: list[PreservedEntry] | None = None,
        removed: list[RemovedEntry] | None = None,
        supplied: list[SuppliedEntry] | None = None,
        assumptions: list[Assumption] | None = None,
        warnings: list[ReportWarning] | None = None,
        fabricated_at_parse: frozenset[str] | set[str] = frozenset(),
    ) -> ConversionResult:
        """Assemble a refused Conversion Report (a completed outcome, not an error; Part 4 §4).

        The full pre-flight `preserved`/`removed` prediction rides along so a pipeline has
        everything it needs to decide whether to supply presets and retry. A strict-mode refusal
        that fires *after* recovery passes the recovery-augmented `preserved`/`removed` so the
        completeness invariant still holds over the refused report. ``warnings`` defaults to the
        pre-flight diff's warnings; a refusal *after* a repair passed its repair hazard
        statements alongside (they lead, mirroring the completed report)."""
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
            preserved=preserved if preserved is not None else diff.preserved,
            removed=removed if removed is not None else diff.removed,
            supplied=supplied or [],
            assumptions=assumptions or [],
            warnings=diff.warnings if warnings is None else warnings,
            refusal=refusal,
        )
        _assert_completeness(report, source, fabricated_at_parse)
        return ConversionResult(report=report, output=None, canonical_out=None, validation=None)

    def _assemble(
        self,
        *,
        stage: str,
        status: str,
        mode: str,
        source_format_id: str,
        source_filename: str | None,
        source_sha256: str | None,
        target_format_id: str,
        target_filename: str | None,
        preserved: list[Any],
        removed: list[Any],
        warnings: list[Any],
        source: CanonicalObject | None = None,
        source_schema_version: str | None = None,
        supplied: list[SuppliedEntry] | None = None,
        assumptions: list[Assumption] | None = None,
        refusal: dict[str, Any] | None = None,
    ) -> ConversionReport:
        # The report's source schema_version comes from a materialized source when one exists
        # (the ordinary path), or is passed directly by the streaming path (which has no whole
        # object). Exactly one is supplied.
        schema_version = source.schema_version if source is not None else source_schema_version
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
                "schema_version": schema_version,
            },
            target={"format_id": target_format_id, "filename": target_filename},
            preserved=list(preserved),
            removed=list(removed),
            supplied=list(supplied or []),
            assumptions=list(assumptions or []),
            warnings=list(warnings),
            refusal=refusal,
        )


def _map_assumptions(
    applied_list: list[AppliedAssumption],
) -> tuple[
    list[Assumption], list[SuppliedEntry], list[PreservedEntry], list[RemovedEntry], set[str]
]:
    """Map the Recovery Engine's plain ``AppliedAssumption`` result types onto the Conversion
    Report's ``Assumption``/``SuppliedEntry``/``PreservedEntry``/``RemovedEntry`` (Part 4 §2–3),
    returning the report entries plus the set of paths a fabrication/retention adds to the write
    plan. Shared by the success path and the (parse-time-only) refusal path so both build the report
    identically."""
    assumptions: list[Assumption] = []
    supplied: list[SuppliedEntry] = []
    preserved: list[PreservedEntry] = []
    removed: list[RemovedEntry] = []
    plan_additions: set[str] = set()
    for applied in applied_list:
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
            # A fabricated field enters the write_plan so it is exported and validated — *unless* it
            # was fabricated only to feed another recovery and the target cannot store it (chained
            # `missing_masses` masses seeding a Maxwell–Boltzmann draw on POSCAR): those are audited
            # in `supplied` but kept out of the write_plan so validation doesn't expect them (D47).
            if sup.in_write_plan:
                plan_additions.add(sup.path)
        for pres in applied.preserved:
            # A selective-reductive choice's *retained* genuine data (e.g. the constraint subset
            # `project` keeps) — Preserved (and written), never Supplied (P4).
            preserved.append(PreservedEntry(path=pres.path, detail=pres.detail))
            plan_additions.add(pres.path)
        for drop in applied.removed:
            removed.append(RemovedEntry(path=drop.path, reason=drop.reason, detail=drop.detail))
    return assumptions, supplied, preserved, removed, plan_additions


def _dedupe_removed(entries: list[RemovedEntry]) -> list[RemovedEntry]:
    """Collapse ``removed`` entries that share a canonical path to the first occurrence, preserving
    order. The same field can be flagged lost by two detectors (a capability-NONE target *and* a
    frame reduction that dropped its only frame); the completeness invariant is path-level, so one
    entry per path keeps the report honest without redundancy."""
    seen: set[str] = set()
    deduped: list[RemovedEntry] = []
    for entry in entries:
        if entry.path not in seen:
            seen.add(entry.path)
            deduped.append(entry)
    return deduped


def _parse_warnings(issues: list[ParseIssue]) -> list[Any]:
    from xtalate.conversion.report import ReportWarning

    # Aggregate per-frame issues before flattening to warnings: a carried-verbatim result on a
    # 1000-frame trajectory is one warning naming the frame range, not 1000 identical lines
    # (Part 3 §5; the v0.7 review, F9). The range rides in the message because ReportWarning has
    # no location field — collapse_frame_issues already folded it there.
    return [
        ReportWarning(code=i.code, message=i.message, source="parse")
        for i in collapse_frame_issues(issues)
        if i.severity == "warning"
    ]


def _append_assumption_records(
    canonical: CanonicalObject,
    rows: list[Assumption],
    *,
    operation: str,
    source_format_id: str,
    target_format_id: str,
) -> CanonicalObject:
    """Append one ``ConversionRecord`` per applied Assumption row (Part 4 §3.2; §2 provenance
    mirroring), so the object stays independently self-explanatory. ``operation`` is
    ``"recovery"`` for recovery rows (the pre-v1.7 behaviour, unchanged) and ``"repair"`` for
    repair rows (v1.7 M64 — activating the reserved ``operation="repair"`` value, §3.9)."""
    if not rows:
        return canonical
    records = [
        ConversionRecord(
            timestamp=_utc_now(),
            operation=operation,
            source_format=source_format_id,
            target_format=target_format_id,
            tool_version=__version__,
            parser_version=None,
            assumptions=[a.id],
        )
        for a in rows
    ]
    return canonical.model_copy(
        update={
            "provenance": canonical.provenance.model_copy(
                update={"history": [*canonical.provenance.history, *records]}
            )
        }
    )


def _repair_rows(applied_list: list[AppliedRepair]) -> list[Assumption]:
    """Map applied repairs onto the report's ``Assumption`` rows — the D249 record triple (a) +
    (b). Each row carries ``scenario=REPAIR_SCENARIO`` (so ``ConversionReport.repairs`` — the
    user-requested section — can derive it), the operation name in ``choice``, the complete
    recorded parameters verbatim (the reproducibility harness's input), ``origin="preset"``
    (repairs are requested up front, like recovery presets), and the plain-language statement in
    ``description``. Repairs fabricate/remove no canonical path, so they produce no
    ``SuppliedEntry``/``RemovedEntry`` of their own."""
    return [
        Assumption(
            id=a.id,
            scenario=REPAIR_SCENARIO,
            choice=a.operation,
            parameters=a.parameters,
            origin="preset",
            description=a.description,
        )
        for a in applied_list
    ]


def _repair_warnings(applied_list: list[AppliedRepair]) -> list[ReportWarning]:
    """The repair hazard statements (D251) as report ``warnings`` rows — each operation's
    transformative-loss records, in application order, ``source="repair"``."""
    return [
        ReportWarning(code=h.code, message=h.message, source="repair")
        for a in applied_list
        for h in a.hazards
    ]


def _repair_block_scenarios(
    blocked: list[RepairBlock],
    matrix: CapabilityMatrix,
    target_format_id: str,
    output_multifile: bool,
) -> list[UnresolvedScenario]:
    """Map blocked repairs onto the recovery scenarios they resolve through (D249/D250).

    M64/M65's closed operation set knows two blocks, both cell-less: ``wrap_into_cell`` and a
    ``center`` whose ``cell_center`` reference/target names a frame without one — both compose
    with the existing ``missing_lattice`` recovery — the scenario, canonical path, and
    pair-specific option list (computed for the concrete target, never static) come from the
    existing machinery, so the repair refuses exactly the way a target-required lattice would
    (nothing new is invented). A block whose reason maps to no recovery scenario raises: the
    engine can neither refuse it through recovery nor honestly proceed."""
    caps = matrix.get(target_format_id, "write")
    scenarios: list[UnresolvedScenario] = []
    for block in blocked:
        if block.reason == REPAIR_BLOCK_MISSING_LATTICE:
            scenarios.append(
                UnresolvedScenario(
                    scenario="missing_lattice",
                    path=block.path or "cell.lattice_vectors",
                    detail=block.detail,
                    options=available_options(
                        "missing_lattice",
                        target_can_be_nonperiodic=caps.allows_open_boundaries,
                        target_supports_multifile=output_multifile,
                    ),
                )
            )
        else:
            raise RepairError(
                f"repair {block.operation!r} blocked for reason {block.reason!r}, which maps to "
                "no recovery scenario in this version — the engine can neither refuse it "
                "through recovery nor proceed"
            )
    return scenarios


def _is_split_all(assumptions: list[Assumption]) -> bool:
    """True iff a ``frame_selection=split_all`` choice was applied — the signal for
    one-file-per-frame export (Part 4 §3.3). The applied Assumption's ``scenario``/``choice`` is the
    sole signal; the recovered object still carries every frame."""
    return any(a.scenario == "frame_selection" and a.choice == "split_all" for a in assumptions)


def _merge_split_validations(validations: list[ValidationReport]) -> ValidationReport:
    """Merge the per-file Validation Reports of a ``split_all`` conversion into one (Part 5 §3: one
    report per completed conversion). The aggregate ``status`` is the worst across files, and each
    *check kind* collapses to a single representative row — the worst outcome for that ``check_id``
    across all files, annotated with the file count and the worst file's index. A 1000-file split
    therefore yields one row per check (~9), not 9000: carrying every file's checks verbatim made a
    report that flooded the CLI (and, before the service declined ``split_all`` over HTTP, the
    API/UI) yet said nothing a per-check worst-case does not. A failure is still locatable via
    ``worst_split_file_index``. Re-parse issues are de-duplicated for the same reason."""
    report_rank = {"passed": 0, "passed_with_warnings": 1, "failed": 2}
    status = max((v.status for v in validations), key=lambda s: report_rank[s])
    n = len(validations)

    # Collapse per ``check_id``: keep the worst-status file's CheckResult for each kind, preserving
    # the order checks first appear (file 0's §2 catalog order). ``skipped`` ranks with ``pass``.
    check_rank = {"pass": 0, "skipped": 0, "warn": 1, "fail": 2}
    worst: dict[str, tuple[int, CheckResult]] = {}
    order: list[str] = []
    for i, v in enumerate(validations):
        for c in v.checks:
            if c.check_id not in worst:
                order.append(c.check_id)
                worst[c.check_id] = (i, c)
            elif check_rank[c.status] > check_rank[worst[c.check_id][1].status]:
                worst[c.check_id] = (i, c)
    checks = [_annotate_split_check(worst[cid][1], worst[cid][0], n) for cid in order]

    # De-duplicate re-parse issues: each single-frame file's re-parse tends to repeat the same
    # warning, so a naive concatenation is another N-fold flood. Order-preserving on first sight.
    seen: set[tuple[str, str, str, str | None]] = set()
    reparse: list[ParseIssue] = []
    for v in validations:
        for issue in v.reparse_issues:
            key = (issue.severity, issue.code, issue.message, issue.location)
            if key not in seen:
                seen.add(key)
                reparse.append(issue)

    return ValidationReport(
        report_id=str(uuid.uuid4()),
        conversion_report_id=validations[0].conversion_report_id,
        created_at=_utc_now(),
        status=status,
        checks=checks,
        tolerance_profile=validations[0].tolerance_profile,
        reparse_issues=reparse,
        schema_version=validations[0].schema_version,
    )


def _annotate_split_check(check: CheckResult, worst_index: int, n_files: int) -> CheckResult:
    """One representative row for a ``check_id`` across a ``split_all`` conversion's ``n_files``
    per-frame files: the worst file's result, tagged (``split_files``, ``worst_split_file_index``)
    so a reader can still locate a failure without the collapsed per-file rows."""
    return check.model_copy(
        update={
            "measured": {
                **check.measured,
                "split_files": n_files,
                "worst_split_file_index": worst_index,
            },
            "message": (
                f"{check.message} · merged from {n_files} per-frame files "
                f"(worst: file {worst_index})"
            ),
        }
    )


def build_expected_object(
    source: CanonicalObject, write_plan: set[str], target_format_id: str
) -> CanonicalObject:
    """Materialize the *expected object* (``canonical′``) from a source object and a container-level
    ``write_plan`` — the public entry the offline full re-parse re-validation uses to reconstruct
    the Validation Engine's reference from a source file and a Conversion Report's path lists
    (Part 5 §4.5). Identical construction to the Conversion Engine's own filtering step."""
    return _apply_write_plan(source, write_plan, target_format_id)


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
        custom_global=_kept_custom(um.custom_global, "user_metadata.custom_global", plan),
        custom_per_atom=_kept_custom(um.custom_per_atom, "user_metadata.custom_per_atom", plan),
        custom_per_frame=_kept_custom(um.custom_per_frame, "user_metadata.custom_per_frame", plan),
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


# The canonical fields a format may declare required that are *always* present in any object
# (schema-required, or the derived mirror), so a required-field recovery can never fire for them —
# the streaming eligibility gate (Part 4 §3.3, M12).
_UNIVERSAL_FIELDS = frozenset({"atoms.symbols", "atoms.positions", "atoms.atomic_numbers"})


def _seekable(stream: Any) -> bool:
    """Whether a binary stream can be re-read from the start — required to re-parse the source
    (expected side) and the just-written output (actual side) for streaming validation (M12)."""
    try:
        return bool(stream.seekable())
    except AttributeError:
        return hasattr(stream, "seek") and hasattr(stream, "read")


def _discard_partial_output(output: Any) -> None:
    """Best-effort clear of a partially-written output stream after a mid-stream failure (Part 3 §5,
    M12): truncate to empty so no half-written frames linger. A stream that cannot be truncated
    (a non-seekable sink) is left as-is — the caller still gets no ConversionResult, so nothing
    presents the partial bytes as a completed conversion; this just clears debris when it can."""
    try:
        output.seek(0)
        output.truncate()
    except (AttributeError, OSError, ValueError):
        pass


def _capability_write_plan(caps: Any) -> set[str]:
    """The write plan implied by a target's capabilities alone (M12): every declared leaf path the
    target can express (FULL or PARTIAL). Presence-independent — an absent field filters to ``None``
    regardless — so it yields the *same* ``canonical′`` per frame as the materialized path's
    presence-derived ``diff.write_plan`` (a plan entry for an absent field is simply never
    exercised). This is what lets a streamed frame be filtered before global presence is seen."""
    return {path for path, cap in caps.fields.items() if cap.level != CapabilityLevel.NONE}


def _filter_stream_frame(sf: StreamFrame, plan: set[str]) -> StreamFrame:
    """Apply the write plan to one streamed frame (M12): filter the scientific ``Frame`` exactly as
    ``_filter_frame`` does, and drop per-frame custom entries the target cannot write — mirroring
    ``_kept_custom`` so a streamed ``canonical′`` frame equals the materialized one."""
    per_frame = _kept_custom(sf.per_frame_custom, "user_metadata.custom_per_frame", plan)
    return StreamFrame(frame=_filter_frame(sf.frame, plan), per_frame_custom=per_frame)


def _filter_stream_header(header: StreamHeader, plan: set[str]) -> StreamHeader:
    """Apply the write plan to the eager stream header (M12): keep only the object-level metadata
    the target can write, mirroring ``_apply_write_plan``'s ``simulation``/``UserMetadata`` handling
    exactly — so the filtered header used as the streaming-validation *expected* side carries the
    identical presence to the materialized ``canonical′``, not just the identical exported bytes."""
    simulation = None
    if header.simulation is not None:
        kept = {
            name: getattr(header.simulation, name)
            for name in _SIMULATION_FIELDS
            if f"simulation.{name}" in plan
        }
        simulation = SimulationMetadata(**kept) if kept else None
    # Mirror _apply_write_plan: keep the trajectory container (multi-frame semantics) but drop the
    # timestep value when the plan excludes it.
    trajectory = header.trajectory
    if trajectory is not None and "trajectory.timestep" not in plan:
        trajectory = TrajectoryMetadata(timestep=None)
    return StreamHeader(
        schema_version=header.schema_version,
        provenance=header.provenance,
        trajectory=trajectory,
        simulation=simulation,
        tags=header.tags if "user_metadata.tags" in plan else [],
        annotations=header.annotations if "user_metadata.annotations" in plan else {},
        custom_global=_kept_custom(header.custom_global, "user_metadata.custom_global", plan),
        custom_per_atom=_kept_custom(header.custom_per_atom, "user_metadata.custom_per_atom", plan),
    )


def _kept_custom(container: dict[str, Any], container_path: str, plan: set[str]) -> dict[str, Any]:
    """Filter a ``custom_*`` container against the write_plan (Part 4 §1). A container-level plan
    entry keeps the whole container (a FULL/PARTIAL target that writes any key — e.g. extXYZ);
    otherwise only keys whose per-key path is planned survive (a target that writes only specific
    keys — e.g. plain XYZ's ``xyz:comment``). The per-key path format mirrors ``field_presence()``
    exactly (``schema.presence``), so a preserved per-key path round-trips through this filter."""
    if container_path in plan:
        return dict(container)
    return {k: v for k, v in container.items() if f"{container_path}['{k}']" in plan}


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


def _assert_completeness(
    report: ConversionReport,
    source: CanonicalObject,
    fabricated_at_parse: frozenset[str] | set[str] = frozenset(),
) -> None:
    """The completeness invariant (Part 4 §2) over a materialized source (review §4.5)."""
    _assert_completeness_presence(report, source.field_presence(), fabricated_at_parse)


def _assert_completeness_presence(
    report: ConversionReport,
    presence: PresenceMap,
    fabricated_at_parse: frozenset[str] | set[str] = frozenset(),
) -> None:
    """The completeness invariant (Part 4 §2), asserted at finalization (review §4.5).

    Every source-present/`mixed` path (bar the derived mirror) must appear in `preserved` ∪
    `removed`; every `supplied` path must be absent on the source and trace to an Assumption.
    A violation is silent loss (P1) or silent fabrication (P4) — the two defects this whole
    project exists to make impossible — so it raises unconditionally, never merely logs.

    Driven by a ``PresenceMap`` (not a whole object) so the streaming Conversion path asserts it
    over its *accumulated* presence, identically to the materialized path (M12; standing rule 3).

    ``fabricated_at_parse`` names paths a *parse-time* recovery fabricated (e.g. ``atoms.symbols``
    via ``missing_species``). They are present in ``source`` (the object is already recovered) but
    were absent from the original file, so they are treated as absent-at-source: excluded from the
    silent-loss sweep (they belong in `supplied`, not `preserved`) and permitted in `supplied`
    (their fabrication is honest, not fabrication-of-existing-data)."""
    accounted = {e.path for e in report.preserved} | {e.path for e in report.removed}
    for entry in presence.entries:
        if (
            entry.status in ("present", "mixed")
            and entry.path not in _DERIVED_PATHS
            and entry.path not in fabricated_at_parse
        ):
            if entry.path not in accounted:
                raise CompletenessInvariantError(
                    f"source-present path {entry.path!r} is in neither preserved nor removed — "
                    "silent loss (P1)"
                )

    # A supplied path may legitimately have been *present* on the source when that source value was
    # itself accounted as `removed` — the honest "dropped the original, fabricated a replacement"
    # case (a `mixed` cell whose cell-bearing frame frame_selection drops, then missing_lattice
    # rebuilds a lattice for the retained frame). Both facts are in the report, so it is not silent;
    # excluding `removed` paths keeps the P4 check catching only fabrication over *kept* data.
    #
    # `mixed` paths are likewise excluded (M13). `mixed` *means* some frames have the field and some
    # do not, so a fabrication that fills only the absent frames is by definition not fabrication
    # over kept data — it is the partial case XDATCAR introduced, reported as `preserved` (the
    # genuine frames) *and* `supplied` (the filled ones). The check keeps its teeth where the risk
    # actually lives: a *uniformly* present path can never need supplying, so supplying one is
    # always overwrite of genuine data and still raises.
    removed_paths = {e.path for e in report.removed}
    uniformly_present = {e.path for e in presence.entries if e.status == "present"}
    source_present = uniformly_present - set(fabricated_at_parse) - removed_paths
    assumption_ids = {a.id for a in report.assumptions}
    for supplied in report.supplied:
        if supplied.path in source_present:
            raise CompletenessInvariantError(
                f"supplied path {supplied.path!r} was present on the source and not removed — "
                "silent fabrication over kept data (P4)"
            )
        if supplied.from_assumption not in assumption_ids:
            raise CompletenessInvariantError(
                f"supplied path {supplied.path!r} references unknown assumption "
                f"{supplied.from_assumption!r}"
            )
