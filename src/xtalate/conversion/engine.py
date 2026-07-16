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
from io import BytesIO
from typing import Any

from xtalate import __version__
from xtalate._time import utc_now as _utc_now
from xtalate.capabilities import Registry
from xtalate.conversion.parse_recovery import ParseRecovery
from xtalate.conversion.preflight import (
    PreflightDiff,
    build_preflight,
    build_preflight_from_presence,
    on_demand_fabricative_scenarios,
)
from xtalate.conversion.report import (
    Assumption,
    ConversionReport,
    PreservedEntry,
    RemovedEntry,
    SuppliedEntry,
)
from xtalate.recovery import AppliedAssumption, RecoveryEngine
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
from xtalate.sdk import CapabilityLevel, ParseIssue, StreamFrame, StreamHeader
from xtalate.validation import ToleranceProfile, ValidationEngine, ValidationReport

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
        parse_issues: list[ParseIssue] | None = None,
        parse_recovery: ParseRecovery | None = None,
        acknowledge_loss: bool = False,
        acknowledge_parse_warnings: bool = False,
        tolerance_profile: str | ToleranceProfile = "default",
    ) -> ConversionResult:
        """Run the conversion end to end and produce the final report (Part 4 §1).

        ``parse_recovery`` carries any *parse-time* recovery (``missing_species``,
        ``truncate_corrupt_tail``) the caller already applied via ``parse_with_recovery`` — its
        Assumptions are merged ahead of pre-flight recovery and land in the report identically."""
        recovery_choices = recovery_choices or {}
        parse_issues = list(parse_issues or [])
        if parse_recovery is not None:
            # The recovery's own warnings (POSCAR_SPECIES_SUPPLIED / XYZ_TRUNCATED) echo into the
            # report like any parse warning (Part 3 §5 rule 5), so the recovery is never silent.
            parse_issues = [*parse_issues, *parse_recovery.issues]
        matrix = self._registry.capability_matrix()
        diff = build_preflight(source, matrix, target_format_id)
        # Opt-in fabricative scenarios (velocity/mass emission) the user requested via
        # `recovery_choices` — not auto-detected by the diff, since the target does not *require*
        # these fields (Part 4 §3.3, D46). Merged with the diff's scenarios before recovery.
        on_demand = on_demand_fabricative_scenarios(
            source, matrix, target_format_id, recovery_choices, mode=mode
        )
        all_scenarios = [*diff.unresolved, *on_demand]

        # Parse-time recovery Assumptions (applied before the object existed) are merged ahead of
        # pre-flight recovery. Their fabricated paths are already present in `source` (it is the
        # recovered object), so they are excluded from the pre-flight `preserved` and treated as
        # absent-at-source by the completeness invariant — they belong in `supplied` (Part 4 §3.3).
        parse_applied = list(parse_recovery.assumptions) if parse_recovery else []
        fabricated_at_parse = {sup.path for a in parse_applied for sup in a.supplied}

        # --- Pre-flight recovery (Part 4 §3) ---------------------------------------------
        recovered = source
        recovery_applied: list[AppliedAssumption] = []
        if all_scenarios:
            outcome = self._recovery.resolve(source, all_scenarios, recovery_choices)
            if outcome.canonical is None:
                # Refusal after a successful parse-time recovery still carries that recovery's
                # Assumptions/supplied so the refused report is complete (Part 4 §2, §3.3).
                for n, applied in enumerate(parse_applied, 1):
                    applied.id = f"A{n}"
                r_assumptions, r_supplied, r_preserved, r_removed, _ = _map_assumptions(
                    parse_applied
                )
                preflight_preserved = [
                    e for e in diff.preserved if e.path not in fabricated_at_parse
                ]
                return self._refuse(
                    source=source,
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
                    assumptions=r_assumptions,
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

        # Merge parse-time (first) and pre-flight recovery Assumptions, renumbering A1.. in
        # application order (Part 4 §5 numbering).
        all_applied = [*parse_applied, *recovery_applied]
        for n, applied in enumerate(all_applied, 1):
            applied.id = f"A{n}"
        assumptions, supplied, recovery_preserved, recovery_removed, plan_additions = (
            _map_assumptions(all_applied)
        )
        write_plan = set(diff.write_plan) | plan_additions

        preflight_preserved = [e for e in diff.preserved if e.path not in fabricated_at_parse]
        preserved = [*preflight_preserved, *recovery_preserved]
        # A path the pre-flight optimistically predicted `preserved` but that recovery then
        # *fabricated* (`supplied`) was not, in fact, carried from the source. The case is a `mixed`
        # cell whose only cell-bearing frame `frame_selection` drops: pre-flight, seeing the cell
        # present in *some* frame, optimistically predicts `cell.lattice_vectors` preserved, but the
        # retained frame is cell-less and `missing_lattice` fills it (D51). `preserved` and
        # `supplied` are mutually exclusive per path — genuine-retained vs fabricated — so a
        # supplied path is struck from `preserved`; it stays in `removed` (the dropped original) and
        # `supplied` (the fabricated replacement), the honest removed+supplied pair D51 promises.
        _supplied_paths = {s.path for s in supplied}
        preserved = [e for e in preserved if e.path not in _supplied_paths]
        # A per-frame path a capability-NONE target already routes to `diff.removed` can *also* be
        # reported lost by `frame_selection` when it lived only in dropped frames — one removal, two
        # detectors. Dedupe by path (the capability diff's entry wins, as the more fundamental
        # reason) so the report never lists the same path removed twice.
        removed = _dedupe_removed([*diff.removed, *recovery_removed])

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
                    preserved=preserved,
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
                    preserved=preserved,
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
            preserved=preserved,
            removed=removed,
            supplied=supplied,
            assumptions=assumptions,
            warnings=warnings,
        )
        _assert_completeness(report, source, fabricated_at_parse)

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

    def streaming_eligible(self, source_format_id: str, target_format_id: str) -> bool:
        """Whether a ``(source, target)`` pair can take the streaming path (M12).

        Eligible iff both plugins stream **and** the target can never *require recovery*: no
        ``max_frames`` cap (would trigger ``frame_selection``), no recovery-able required field that
        could be absent (only the universally-present ``atoms.*`` are allowed), and no PARTIAL
        constraint capability (would trigger ``constraint_representation``). These are all static
        capability facts, decided before a byte is read — a conversion that *might* need a recovery
        choice mid-stream (which the streaming path does not yet resolve — M12 cut line) falls back
        to the materialized ``convert``. extXYZ→extXYZ, the trajectory pass-through, qualifies."""
        parser = self._registry.get_parser(source_format_id)
        exporter = self._registry.get_exporter(target_format_id)
        if not (parser.supports_streaming() and exporter.supports_streaming()):
            return False
        matrix = self._registry.capability_matrix()
        caps = matrix.get(target_format_id, "write")
        if caps.max_frames is not None:
            return False
        if any(r not in _UNIVERSAL_FIELDS for r in caps.required_fields):
            return False
        constraints = matrix.field_capability(target_format_id, "write", "dynamics.constraints")
        return constraints.level != CapabilityLevel.PARTIAL

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

        Only ``streaming_eligible`` pairs are accepted; anything that could need a recovery choice
        raises ``ValueError`` (use ``convert``). ``validate`` re-parses the written ``output``
        through the ordinary Validation Engine when the stream is seekable; full *streaming*
        validation (frame-pairwise, deliverable 4) is the documented M12 follow-up, so this re-parse
        is bounded by the output size, not folded into the single input pass.
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
                yield _filter_stream_frame(sf, write_plan)

        # The exporter writes each planned frame as it is yielded — the single streamed pass.
        filtered_header = _filter_stream_header(header, write_plan)
        exporter.export_stream(filtered_header, _planned_frames(), output)

        presence = acc.result()
        diff = build_preflight_from_presence(
            presence,
            frame_count=counters["frames"],
            has_constraints=False,  # constraint targets are ineligible; no frame carries a subset
            matrix=matrix,
            target_format_id=target_format_id,
        )
        preserved = [*diff.preserved, *diff.pending]
        removed = diff.removed
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
        if validate and hasattr(output, "seek") and hasattr(output, "read"):
            tolerance = (
                tolerance_profile
                if isinstance(tolerance_profile, ToleranceProfile)
                else ToleranceProfile.named(tolerance_profile)
            )
            output.seek(0)
            output_bytes = output.read()
            # The expected object is the materialized stream filtered through the write plan — the
            # canonical′ the Validation Engine diffs against (Part 5 §1). Materializing re-reads
            # the just-written output only; streaming validation (frame-pairwise) is the M12 D4
            # follow-up.
            expected, _ = self._materialized_expected(
                parser, source_stream, write_plan, source_filename, target_format_id
            )
            validation = self._validation.validate(
                expected=expected,
                output=output_bytes,
                target_format_id=target_format_id,
                conversion_report=report,
                tolerance=tolerance,
            )
        return ConversionResult(
            report=report, output=None, canonical_out=None, validation=validation
        )

    def _materialized_expected(
        self,
        parser: Any,
        source_stream: Any,
        write_plan: set[str],
        source_filename: str | None,
        target_format_id: str,
    ) -> tuple[CanonicalObject, list[ParseIssue]]:
        """Rebuild the expected object (``canonical′``) for streaming validation by re-reading the
        source stream and applying the write plan — the same filtering ``convert`` performs, so the
        two paths validate against the identical reference."""
        from xtalate.sdk.streaming import materialize

        source_stream.seek(0)
        restream = parser.parse_stream(source_stream, filename=source_filename)
        source_obj, issues = materialize(restream)
        expected = _apply_write_plan(source_obj, write_plan, target_format_id)
        return expected, issues

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
        fabricated_at_parse: frozenset[str] | set[str] = frozenset(),
    ) -> ConversionResult:
        """Assemble a refused Conversion Report (a completed outcome, not an error; Part 4 §4).

        The full pre-flight `preserved`/`removed` prediction rides along so a pipeline has
        everything it needs to decide whether to supply presets and retry. A strict-mode refusal
        that fires *after* recovery passes the recovery-augmented `preserved`/`removed` so the
        completeness invariant still holds over the refused report."""
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
            warnings=diff.warnings,
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


def _is_split_all(assumptions: list[Assumption]) -> bool:
    """True iff a ``frame_selection=split_all`` choice was applied — the signal for
    one-file-per-frame export (Part 4 §3.3). The applied Assumption's ``scenario``/``choice`` is the
    sole signal; the recovered object still carries every frame."""
    return any(a.scenario == "frame_selection" and a.choice == "split_all" for a in assumptions)


def _merge_split_validations(validations: list[ValidationReport]) -> ValidationReport:
    """Merge the per-file Validation Reports of a ``split_all`` conversion into one (Part 5 §3: one
    report per completed conversion). The aggregate ``status`` is the worst across files; each
    file's checks are carried through, tagged with ``split_file_index`` so a failure is located."""
    rank = {"passed": 0, "passed_with_warnings": 1, "failed": 2}
    status = max((v.status for v in validations), key=lambda s: rank[s])
    checks = [
        c.model_copy(update={"measured": {**c.measured, "split_file_index": i}})
        for i, v in enumerate(validations)
        for c in v.checks
    ]
    return ValidationReport(
        report_id=str(uuid.uuid4()),
        conversion_report_id=validations[0].conversion_report_id,
        created_at=_utc_now(),
        status=status,
        checks=checks,
        tolerance_profile=validations[0].tolerance_profile,
        reparse_issues=[issue for v in validations for issue in v.reparse_issues],
        schema_version=validations[0].schema_version,
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
    the target can write, mirroring ``_apply_write_plan``'s ``UserMetadata``/container handling so
    the streamed output carries exactly what the materialized path would."""
    return StreamHeader(
        schema_version=header.schema_version,
        provenance=header.provenance,
        # The trajectory container carries only multi-frame semantics (its timestep is dropped by
        # the report, never written by a streaming exporter), so it passes through untouched.
        trajectory=header.trajectory,
        simulation=header.simulation,
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
    removed_paths = {e.path for e in report.removed}
    source_present = set(presence.present_paths()) - set(fabricated_at_parse) - removed_paths
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
