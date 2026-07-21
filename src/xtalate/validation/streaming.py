"""Chunk-aware (streaming) validation (MASTER_SPEC Part 5 §2; M12 deliverable 4).

The streaming twin of ``ValidationEngine.validate``: it re-parses the output and diffs it against
the expected object **frame-pairwise over two streams**, holding at most one expected/actual frame
pair resident instead of two whole trajectories. Per-frame checks (``atom_count``, ``species``,
``positions_rmsd``, ``lattice_consistency``, ``numeric_field_fidelity``) fold each pair into running
state; whole-object checks (``frame_count``, ``metadata_preservation``, ``absence_conformance``,
``report_consistency``) run on accumulated state (frame counts, two ``PresenceAccumulator``s, and
the two eager stream headers). Every check is mirrored **exactly** from ``validation.engine`` — the
batch and streaming validators produce the identical ``ValidationReport`` on the same input
(standing rule 3), pinned by ``tests/streaming/test_streaming_validation.py``.

This lives beside the batch engine, importing its check *helpers* (``_permuted``,
``_representational_bound``, ``_field_value``, ``_content_matches``…) so there is one implementation
of the arithmetic — the streaming validator only changes *when* each frame is seen, never *what* a
check computes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, BinaryIO

import numpy as np

from xtalate._time import utc_now
from xtalate.schema import Frame, PresenceAccumulator
from xtalate.sdk import ParseError, StreamFrame, StreamHeader, stream_of
from xtalate.validation._shared import AGGREGATE as _AGGREGATE
from xtalate.validation._shared import NUMERIC_FIELDS as _NUMERIC_FIELDS
from xtalate.validation._shared import RANK as _RANK
from xtalate.validation._shared import require_supported_precision
from xtalate.validation.engine import (
    ConversionReportView,
    _content_matches_values,
    _field_value,
    _permuted,
    _representational_bound,
)
from xtalate.validation.report import CheckResult, ValidationReport
from xtalate.validation.tolerance import ToleranceProfile

if TYPE_CHECKING:
    from xtalate.capabilities import Registry
    from xtalate.sdk import FrameStream


class StreamingValidator:
    """Online realization of the Part 5 §2 check catalog, folded over expected/actual frame pairs.

    Drive it: ``observe_headers`` once, ``observe_pair`` per zipped ``(expected, actual)`` frame,
    then ``finalize``. The state variables mirror the local variables of the corresponding batch
    check functions exactly, so ``finalize`` reconstructs their ``CheckResult`` byte for byte."""

    def __init__(
        self, tolerance: ToleranceProfile, precision: dict[str, int | None], perm: list[int] | None
    ) -> None:
        self._tol = tolerance
        self._precision = precision
        self._perm = perm
        self._n = 0  # frame pairs compared

        # atom_count
        self._ac_exp0 = 0
        self._ac_got0 = 0
        self._ac_mismatches: list[int] = []

        # species_preservation
        self._sp_mismatches = 0

        # positions_rmsd
        self._pos_bound = _representational_bound(precision, "atoms.positions")
        self._pos_eff = tolerance.effective("positions", self._pos_bound)
        self._pos_max_rmsd = 0.0
        self._pos_max_disp = 0.0
        self._pos_shape_fail: tuple[tuple[int, ...], tuple[int, ...]] | None = None

        # lattice_consistency
        self._lat_bound = _representational_bound(precision, "cell.lattice_vectors")
        self._lat_eff = tolerance.effective("lattice", self._lat_bound)
        self._lat_have = False
        self._lat_max_diff = 0.0
        self._lat_pbc_mismatch = False
        self._lat_pbc_exp: list[bool] = []
        self._lat_pbc_got: list[bool] = []
        self._lat_absent_frame: int | None = None

        # numeric_field_fidelity — per path running max + missing flag + any-expected flag
        self._num: dict[str, dict[str, Any]] = {
            path: {"field_max": 0.0, "missing": False, "any": False, "quantity": q, "kind": k}
            for path, q, k in _NUMERIC_FIELDS
        }

        # presence accumulators for metadata / absence (schema_version filled at finalize)
        self._exp_presence = PresenceAccumulator("")
        self._act_presence = PresenceAccumulator("")
        self._exp_header: StreamHeader | None = None
        self._act_header: StreamHeader | None = None

    def observe_headers(self, expected: StreamHeader, actual: StreamHeader) -> None:
        self._exp_header = expected
        self._act_header = actual
        for acc, h in ((self._exp_presence, expected), (self._act_presence, actual)):
            acc.observe_header(
                trajectory=h.trajectory,
                simulation=h.simulation,
                tags=h.tags,
                annotations=h.annotations,
                custom_global=h.custom_global,
                custom_per_atom=h.custom_per_atom,
            )

    def observe_pair(self, i: int, expected: StreamFrame, actual: StreamFrame) -> None:
        ef, af = expected.frame, actual.frame
        self._observe_presence(self._exp_presence, expected)
        self._observe_presence(self._act_presence, actual)
        self._fold_atom_count(i, ef, af)
        self._fold_species(ef, af)
        self._fold_positions(ef, af)
        self._fold_lattice(i, ef, af)
        self._fold_numeric(ef, af)
        self._n += 1

    def observe_expected_tail(self, expected: StreamFrame) -> None:
        """Fold an expected frame with no actual counterpart (the output has fewer frames): its
        presence still counts toward ``frame_count`` and ``metadata``, but there is no pair to check
        — as the batch checks iterate only ``min(len(expected), len(canonical))`` pairs while
        ``frame_count``/``metadata`` read the full objects."""
        self._observe_presence(self._exp_presence, expected)

    def observe_actual_tail(self, actual: StreamFrame) -> None:
        """Fold an actual (re-parsed output) frame with no expected counterpart (the output has more
        frames): counts toward ``frame_count`` and ``absence``, no pair to check."""
        self._observe_presence(self._act_presence, actual)

    @staticmethod
    def _observe_presence(acc: PresenceAccumulator, sf: StreamFrame) -> None:
        acc.observe_frame(sf.frame, [k for k, v in sf.per_frame_custom.items() if v is not None])

    # -- per-frame folds (mirror the batch checks exactly) ----------------------------

    def _fold_atom_count(self, i: int, ef: Frame, af: Frame) -> None:
        if i == 0:
            self._ac_exp0 = len(ef.atoms.symbols)
            self._ac_got0 = len(af.atoms.symbols)
        if len(ef.atoms.symbols) != len(af.atoms.symbols):
            self._ac_mismatches.append(i)

    def _fold_species(self, ef: Frame, af: Frame) -> None:
        exp, got = ef.atoms.symbols, af.atoms.symbols
        if len(exp) != len(got):
            self._sp_mismatches += max(len(exp), len(got))
            return
        order = self._perm if self._perm is not None else list(range(len(exp)))
        self._sp_mismatches += sum(1 for j in range(len(got)) if exp[order[j]] != got[j])

    def _fold_positions(self, ef: Frame, af: Frame) -> None:
        if self._pos_shape_fail is not None:
            return
        exp = _permuted(np.asarray(ef.atoms.positions, dtype=float), self._perm)
        got = np.asarray(af.atoms.positions, dtype=float)
        if exp.shape != got.shape:
            self._pos_shape_fail = (exp.shape, got.shape)
            return
        disp = np.linalg.norm(got - exp, axis=1)
        rmsd = float(np.sqrt(np.mean(disp**2))) if disp.size else 0.0
        self._pos_max_rmsd = max(self._pos_max_rmsd, rmsd)
        self._pos_max_disp = max(self._pos_max_disp, float(disp.max()) if disp.size else 0.0)

    def _fold_lattice(self, i: int, ef: Frame, af: Frame) -> None:
        if ef.cell is None or self._lat_absent_frame is not None:
            return
        self._lat_have = True
        if af.cell is None:
            self._lat_absent_frame = i
            return
        e = np.asarray(ef.cell.lattice_vectors, dtype=float)
        g = np.asarray(af.cell.lattice_vectors, dtype=float)
        self._lat_max_diff = max(self._lat_max_diff, float(np.abs(e - g).max()))
        self._lat_pbc_exp = [bool(x) for x in ef.cell.pbc]
        self._lat_pbc_got = [bool(x) for x in af.cell.pbc]
        if self._lat_pbc_exp != self._lat_pbc_got:
            self._lat_pbc_mismatch = True

    def _fold_numeric(self, ef: Frame, af: Frame) -> None:
        for path, state in self._num.items():
            ev = _field_value(ef, path)
            if ev is None:
                continue
            state["any"] = True
            gv = _field_value(af, path)
            if gv is None:
                state["missing"] = True
                continue
            e = np.asarray(ev, dtype=float)
            g = np.asarray(gv, dtype=float)
            if state["kind"] == "per_atom":
                e = _permuted(e, self._perm)
            if e.shape != g.shape:
                state["missing"] = True
                continue
            state["field_max"] = max(
                state["field_max"], float(np.abs(e - g).max()) if e.size else 0.0
            )

    # -- finalize ---------------------------------------------------------------------

    def finalize(
        self,
        conversion_report: ConversionReportView,
        schema_version: str,
        reparse_issues: list[Any],
    ) -> ValidationReport:
        checks = [
            self._atom_count_result(),
            self._species_result(),
            self._positions_result(),
            self._lattice_result(),
            self._frame_count_result(),
            self._numeric_result(),
            self._metadata_result(),
            self._absence_result(conversion_report),
            _report_consistency_result(conversion_report),
        ]
        worst = max((_RANK[c.status] for c in checks), default=0)
        if reparse_issues and worst == 0:
            worst = 1
        return ValidationReport(
            report_id=str(uuid.uuid4()),
            conversion_report_id=conversion_report.report_id,
            created_at=utc_now(),
            status=_AGGREGATE[worst],
            checks=checks,
            tolerance_profile=self._tol.as_dict(),  # type: ignore[arg-type]
            reparse_issues=reparse_issues,
            schema_version=schema_version,
        )

    def _atom_count_result(self) -> CheckResult:
        status = "fail" if self._ac_mismatches else "pass"
        return CheckResult(
            check_id="atom_count",
            status=status,
            paths=["atoms.symbols"],
            measured={
                "expected": self._ac_exp0,
                "found": self._ac_got0,
                "frames_compared": self._n,
            },
            message=(
                f"{self._ac_exp0} atoms expected, {self._ac_got0} found (exact check)."
                if status == "pass"
                else f"atom-count mismatch in frame(s) {self._ac_mismatches} — a dropped or "
                "duplicated atom."
            ),
        )

    def _species_result(self) -> CheckResult:
        status = "fail" if self._sp_mismatches else "pass"
        measured: dict[str, Any] = {
            "permutation_map": self._perm if self._perm is not None else "identity",
            "mismatches": self._sp_mismatches,
        }
        if status == "pass":
            grouping = (
                " under the exporter's element grouping (permutation map applied)."
                if self._perm is not None
                else "; source order retained (identity permutation)."
            )
            message = "Species preserved" + grouping
        else:
            message = (
                f"{self._sp_mismatches} element mismatch(es) after the permutation map — "
                "chemistry lost"
            )
        return CheckResult(
            check_id="species_preservation",
            status=status,
            paths=["atoms.symbols"],
            measured=measured,
            message=message,
        )

    def _positions_result(self) -> CheckResult:
        eff = self._pos_eff
        if self._pos_shape_fail is not None:
            exp, got = self._pos_shape_fail
            return _shape_fail_result("positions_rmsd", ["atoms.positions"], exp, got)
        rmsd = self._pos_max_rmsd
        status = "fail" if rmsd > eff.fail else "warn" if rmsd > eff.warn else "pass"
        return CheckResult(
            check_id="positions_rmsd",
            status=status,
            paths=["atoms.positions"],
            measured={
                "rmsd_ang": rmsd,
                "max_displacement_ang": self._pos_max_disp,
                "frames_compared": self._n,
            },
            tolerance_applied={
                "warn_ang": eff.warn,
                "fail_ang": eff.fail,
                "representational_bound_ang": self._pos_bound,
            },
            message=(
                f"RMSD {rmsd:.3e} Å over {self._n} frame(s), within representational precision."
                if status == "pass"
                else f"RMSD {rmsd:.3e} Å over {self._n} frame(s) exceeds the {status} threshold "
                f"{(eff.fail if status == 'fail' else eff.warn):.3e} Å."
            ),
        )

    def _lattice_result(self) -> CheckResult:
        if not self._lat_have:
            return CheckResult(
                check_id="lattice_consistency",
                status="skipped",
                paths=["cell.lattice_vectors", "cell.pbc"],
                message="No lattice in the write plan — nothing to compare.",
                skip_reason="write_plan contains no cell.lattice_vectors.",
            )
        if self._lat_absent_frame is not None:
            return CheckResult(
                check_id="lattice_consistency",
                status="fail",
                paths=["cell.lattice_vectors", "cell.pbc"],
                measured={"frame": self._lat_absent_frame},
                message=(
                    f"planned lattice absent from re-parsed output in frame "
                    f"{self._lat_absent_frame}."
                ),
            )
        eff = self._lat_eff
        max_diff = self._lat_max_diff
        pbc_exp = self._lat_pbc_exp
        if self._lat_pbc_mismatch or max_diff > eff.fail:
            status = "fail"
        elif max_diff > eff.warn:
            status = "warn"
        else:
            status = "pass"
        measured: dict[str, Any] = {
            "max_element_diff_ang": max_diff,
            "pbc_expected": pbc_exp,
            "pbc_found": self._lat_pbc_got,
        }
        return CheckResult(
            check_id="lattice_consistency",
            status=status,
            paths=["cell.lattice_vectors", "cell.pbc"],
            measured=measured,
            tolerance_applied={"warn_ang": eff.warn, "fail_ang": eff.fail},
            message=(
                f"Lattice matches within {max_diff:.3e} Å; pbc {pbc_exp} preserved exactly."
                if status == "pass"
                else (
                    "pbc mismatch (booleans admit no tolerance)."
                    if self._lat_pbc_mismatch
                    else f"lattice element diff {max_diff:.3e} Å exceeds the {status} threshold."
                )
            ),
        )

    def _frame_count_result(self) -> CheckResult:
        exp = self._exp_presence.frame_count
        got = self._act_presence.frame_count
        status = "pass" if exp == got else "fail"
        return CheckResult(
            check_id="frame_count",
            status=status,
            paths=["frames"],
            measured={"expected": exp, "found": got},
            message=(
                f"{exp} frame(s) planned, {got} found."
                if status == "pass"
                else f"frame-count mismatch: {exp} planned, {got} found."
            ),
        )

    def _numeric_result(self) -> CheckResult:
        measured: dict[str, Any] = {}
        paths: list[str] = []
        worst = "pass"
        for path, state in self._num.items():
            if not state["any"]:
                continue
            paths.append(path)
            bound = _representational_bound(self._precision, path)
            eff = self._tol.effective(state["quantity"], bound)
            field_max = state["field_max"]
            if state["missing"]:
                status = "fail"
            else:
                status = (
                    "fail" if field_max > eff.fail else "warn" if field_max > eff.warn else "pass"
                )
            measured[path] = {
                "max_abs_diff": field_max,
                "warn": eff.warn,
                "fail": eff.fail,
                "missing": state["missing"],
                # Recorded per path so an offline re-threshold can reproduce this judgement. The
                # scalar checks carry their bound in `tolerance_applied`; this check judges eight
                # paths at once, so a single slot cannot hold it and the re-thresholder was
                # silently re-judging without one (tightening the tolerance it re-applied).
                "representational_bound": bound,
            }
            if _RANK[status] > _RANK[worst]:
                worst = status
        if not paths:
            return CheckResult(
                check_id="numeric_field_fidelity",
                status="skipped",
                paths=[],
                message="No numeric fields beyond positions and lattice in the write plan.",
                skip_reason="write_plan contains no velocities, forces, energies, stress, charges, "
                "magnetic moments, masses, or time.",
            )
        return CheckResult(
            check_id="numeric_field_fidelity",
            status=worst,
            paths=paths,
            measured=measured,
            message=(
                f"{len(paths)} numeric field(s) faithful within per-quantity tolerance."
                if worst == "pass"
                else f"numeric fidelity {worst} on one or more of {paths}."
            ),
        )

    def _metadata_result(self) -> CheckResult:
        exp_presence = self._exp_presence.result()
        act_presence = self._act_presence.result()
        planned = [
            p
            for p in exp_presence.present_paths()
            if p.startswith("simulation.") or p.startswith("user_metadata.")
        ]
        assert self._exp_header is not None and self._act_header is not None
        absent: list[str] = []
        drift = 0
        for path in planned:
            if act_presence.status_of(path) == "absent":
                absent.append(path)
                continue
            if not _content_matches_values(
                self._exp_header.custom_global, self._act_header.custom_global, path
            ):
                drift += 1
        status = "fail" if absent else "warn" if drift else "pass"
        return CheckResult(
            check_id="metadata_preservation",
            status=status,
            paths=planned,
            measured={
                "planned_paths": len(planned),
                "present": len(planned) - len(absent),
                "content_drift": drift,
            },
            message=(
                (
                    f"{len(planned)} planned metadata path(s) present and semantically identical."
                    if planned
                    else "No metadata or custom-array paths in the write plan."
                )
                if status == "pass"
                else (
                    f"planned metadata path(s) absent from output: {absent}."
                    if absent
                    else f"{drift} metadata path(s) changed content on re-parse."
                )
            ),
        )

    def _absence_result(self, report: ConversionReportView) -> CheckResult:
        preserved_paths = {e.path for e in report.preserved}
        supplied_paths = {e.path for e in report.supplied}
        to_check = [
            e.path
            for e in report.removed
            if e.path not in preserved_paths and e.path not in supplied_paths
        ]
        presence = self._act_presence.result()
        violations = [p for p in to_check if presence.status_of(p) != "absent"]
        status = "fail" if violations else "pass"
        return CheckResult(
            check_id="absence_conformance",
            status=status,
            paths=to_check,
            measured={"removed_paths_checked": len(to_check), "violations": len(violations)},
            message=(
                f"All {len(to_check)} removed path(s) verified absent in the re-parse."
                if status == "pass"
                else f"removed path(s) reappeared — exporter deviated from the plan: {violations}"
            ),
        )


def _report_consistency_result(report: ConversionReportView) -> CheckResult:
    assumption_ids = {a.id for a in report.assumptions}
    untraceable = [s.path for s in report.supplied if s.from_assumption not in assumption_ids]
    status = "fail" if untraceable else "pass"
    return CheckResult(
        check_id="report_consistency",
        status=status,
        paths=[],
        measured={
            "completeness_invariant": "satisfied",
            "supplied_traced": len(report.supplied) - len(untraceable),
            "untraceable_deltas": len(untraceable),
            "preflight_final_deltas": len(report.assumptions),
        },
        message=(
            "Completeness invariant satisfied; every supplied path traces to a recorded Assumption."
            if status == "pass"
            else f"supplied path(s) reference an unknown Assumption: {untraceable}."
        ),
    )


def _shape_fail_result(
    check_id: str, paths: list[str], exp: tuple[int, ...], got: tuple[int, ...]
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        status="fail",
        paths=paths,
        measured={"expected_shape": list(exp), "found_shape": list(got)},
        message=f"array shape mismatch: expected {exp}, found {got}.",
    )


def validate_stream(
    registry: Registry,
    *,
    expected: FrameStream,
    output_stream: BinaryIO,
    target_format_id: str,
    conversion_report: ConversionReportView,
    tolerance: ToleranceProfile,
    expected_schema_version: str,
) -> ValidationReport:
    """Chunk-aware validation entry point (M12 deliverable 4): re-parse ``output_stream`` and diff
    it against the ``expected`` frame stream frame-pairwise, holding one frame pair resident.

    A free function (not a ``ValidationEngine`` method) so ``validation.streaming`` can import the
    batch engine's check helpers without the engine importing back — one arithmetic, streamed time.
    Mirrors the batch engine's contract: a re-parse that raises ``ParseError`` becomes a single
    failing ``reparse`` check rather than an exception. ``perm`` is identity — the streaming
    eligibility gate (Part 4 §3.3) admits only order-preserving exporters, so no permutation map is
    needed (a reordering streaming target would thread one, and is excluded until one exists).
    """
    parser = registry.get_parser(target_format_id)
    caps = registry.get_exporter(target_format_id).capabilities()
    precision = require_supported_precision(
        target_format_id, caps.numeric_precision, caps.native_coordinate_system
    )
    validator = StreamingValidator(tolerance, precision, perm=None)
    try:
        if parser.supports_streaming():
            actual = parser.parse_stream(output_stream, filename=None)
        else:
            result = parser.parse(output_stream, filename=None)
            actual = stream_of(result.canonical, issues=list(result.issues))
        validator.observe_headers(expected.header, actual.header)
        drive(validator, expected.frames(), actual.frames())
        reparse_issues: list[Any] = list(actual.issues)
    except ParseError as exc:
        return _reparse_fail_report(conversion_report, expected_schema_version, tolerance, exc)
    return validator.finalize(conversion_report, expected_schema_version, reparse_issues)


def _reparse_fail_report(
    report: ConversionReportView,
    schema_version: str,
    tolerance: ToleranceProfile,
    exc: ParseError,
) -> ValidationReport:
    """The output did not re-parse — the most damning finding possible (Part 5 §1), reported as one
    failing ``reparse`` check exactly as the batch engine does, so a streamed and a batch validation
    of an unreadable output agree."""
    return ValidationReport(
        report_id=str(uuid.uuid4()),
        conversion_report_id=report.report_id,
        created_at=utc_now(),
        status="failed",
        checks=[
            CheckResult(
                check_id="reparse",
                status="fail",
                message=f"output file does not re-parse: {exc}",
            )
        ],
        tolerance_profile=tolerance.as_dict(),  # type: ignore[arg-type]
        reparse_issues=exc.issues,
        schema_version=schema_version,
    )


def drive(
    validator: StreamingValidator,
    expected: Iterator[StreamFrame],
    actual: Iterator[StreamFrame],
) -> None:
    """Pair two frame streams into ``observe_pair`` for the common prefix, then drain whichever
    stream is longer into the matching tail observer. The per-frame checks run only on paired frames
    (mirroring the batch ``min`` iteration), while ``frame_count``/``metadata``/``absence`` see all
    frame of both streams — so a frame-count mismatch is detected, never swallowed."""
    i = 0
    while True:
        e = next(expected, None)
        a = next(actual, None)
        if e is not None and a is not None:
            validator.observe_pair(i, e, a)
            i += 1
            continue
        if e is not None:
            validator.observe_expected_tail(e)
            for rest in expected:
                validator.observe_expected_tail(rest)
        if a is not None:
            validator.observe_actual_tail(a)
            for rest in actual:
                validator.observe_actual_tail(rest)
        return
