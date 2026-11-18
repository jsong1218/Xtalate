"""Structural-fidelity comparison shared by the batch and streaming validators.

Compares the per-frame structural fields no other check covers: ``atoms.occupancies``,
``dynamics.constraints`` (selective-dynamics masks and fixed-atom indices), ``cell.space_group`` and
the carried LAMMPS image flags. One pure tally serves both validators, so reports agree.

A path the Conversion Report already lists under ``removed`` is skipped: its absence is verified by
``absence_conformance``, and failing it here would double-report a disclosed loss. Only an
*unreported* loss or drift fails. The check is emitted only when the expected object carries at
least one structural field and one such path is not in ``removed``, so every existing report is
unchanged. Occupancies keep the P3 distinction between "unknown" (a ``None`` site) and a number: the
``None`` masks must agree, and only sites known on both sides are compared numerically.
"""

from __future__ import annotations

import math

import numpy as np
from pydantic import JsonValue

from xtalate.schema import Frame
from xtalate.sdk.image_flags import IMAGE_FLAGS_CARRY_KEY
from xtalate.validation.report import CheckResult
from xtalate.validation.tolerance import ToleranceProfile

CHECK_ID = "structural_fidelity"
_OCC = "atoms.occupancies"
_CON = "dynamics.constraints"
_SG = "cell.space_group"
_FLAGS = f"user_metadata.custom_per_atom['{IMAGE_FLAGS_CARRY_KEY}']"
_ORDER = (_OCC, _CON, _SG, _FLAGS)


def _source_index(perm: list[int] | None, n: int) -> list[int]:
    """Output position ``i`` holds source atom ``perm[i]``; identity when there is no map."""
    if perm is None or len(perm) != n:
        return list(range(n))
    return [int(p) for p in perm]


def _indexable(src: list[int], length: int) -> bool:
    """Whether every source index addresses a row of a ``length``-row array. A malformed object (a
    short per-atom array, an out-of-range permutation) fails closed rather than raising (M6)."""
    return all(0 <= p < length for p in src)


def _selective_mask(frame: Frame) -> np.ndarray | None:
    for con in frame.dynamics.constraints or []:
        if con.kind == "selective_dynamics" and "mask" in con.parameters:
            mask: np.ndarray = np.asarray(con.parameters["mask"], dtype=bool)
            return mask
    return None


def _fixed_atoms(frame: Frame) -> set[int] | None:
    found = False
    out: set[int] = set()
    for con in frame.dynamics.constraints or []:
        if con.kind == "fixed_atoms":
            found = True
            out.update(con.atom_indices)
    return out if found else None


class StructuralTally:
    """Accumulates structural mismatches over compared frame pairs."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._failed: dict[str, int] = {}
        self._worst_occ = 0.0
        self._frames = 0

    def _fail(self, path: str) -> None:
        self._failed[path] = self._failed.get(path, 0) + 1

    def observe(self, expected: Frame, actual: Frame, perm: list[int] | None) -> None:
        self._frames += 1
        n = len(expected.atoms.symbols)
        src = _source_index(perm, n)

        exp_occ = expected.atoms.occupancies
        if exp_occ is not None:
            self._seen.add(_OCC)
            got_occ = actual.atoms.occupancies
            if (
                got_occ is None
                or len(got_occ) != n
                or len(exp_occ) != n
                or not _indexable(src, len(exp_occ))
            ):
                self._fail(_OCC)
            else:
                bad = False
                for i in range(n):
                    e, a = exp_occ[src[i]], got_occ[i]
                    if (e is None) != (a is None):
                        bad = True  # unknown vs known: never reconciled by a number (P3)
                    elif e is not None and a is not None:
                        diff = abs(float(e) - float(a))
                        if math.isnan(diff):
                            bad = True
                        else:
                            self._worst_occ = max(self._worst_occ, diff)
                if bad:
                    self._fail(_OCC)

        if expected.dynamics.constraints:
            self._seen.add(_CON)
            if not self._constraints_match(expected, actual, src):
                self._fail(_CON)

        if expected.cell is not None and expected.cell.space_group is not None:
            self._seen.add(_SG)
            if actual.cell is None or actual.cell.space_group != expected.cell.space_group:
                self._fail(_SG)

        flags = expected.custom_per_atom.get(IMAGE_FLAGS_CARRY_KEY)
        if flags is not None:
            self._seen.add(_FLAGS)
            got = actual.custom_per_atom.get(IMAGE_FLAGS_CARRY_KEY)
            if got is None:
                self._fail(_FLAGS)
            else:
                e_all = np.asarray(flags, dtype=np.float64)
                if e_all.ndim == 0 or e_all.shape[0] != n or not _indexable(src, n):
                    self._fail(_FLAGS)
                else:
                    e_arr = e_all[src]
                    g_arr = np.asarray(got, dtype=np.float64)
                    if e_arr.shape != g_arr.shape or not bool(np.array_equal(e_arr, g_arr)):
                        self._fail(_FLAGS)

    @staticmethod
    def _constraints_match(expected: Frame, actual: Frame, src: list[int]) -> bool:
        if not actual.dynamics.constraints:
            return False
        exp_mask = _selective_mask(expected)
        if exp_mask is not None:
            got_mask = _selective_mask(actual)
            if got_mask is None or got_mask.shape != exp_mask.shape:
                return False
            n = len(expected.atoms.symbols)
            if exp_mask.ndim == 0 or exp_mask.shape[0] != n or not _indexable(src, n):
                return False
            if not bool(np.array_equal(exp_mask[src], got_mask)):
                return False
        exp_fixed = _fixed_atoms(expected)
        if exp_fixed is not None:
            got_fixed = _fixed_atoms(actual)
            if got_fixed is None:
                return False
            # Output index j is source atom src[j]: map the re-parsed indices back to source space.
            if {src[j] for j in got_fixed if 0 <= j < len(src)} != exp_fixed:
                return False
        return True

    def result(
        self,
        tolerance: ToleranceProfile,
        representational_bound: float,
        removed_paths: frozenset[str],
    ) -> CheckResult | None:
        judged = [p for p in _ORDER if p in self._seen and p not in removed_paths]
        if not judged:
            return None
        eff = tolerance.effective("occupancies", representational_bound)
        failed = [p for p in judged if p in self._failed]
        occ_warn = False
        if _OCC in judged and _OCC not in failed:
            if self._worst_occ > eff.fail:
                failed.append(_OCC)
            elif self._worst_occ > eff.warn:
                occ_warn = True
        measured: dict[str, JsonValue] = {
            "frames_compared": self._frames,
            "max_occupancy_abs_diff": self._worst_occ,
            "failed_paths": list[JsonValue](sorted(failed)),
        }
        applied: dict[str, JsonValue] = {
            "occupancies_warn": eff.warn,
            "occupancies_fail": eff.fail,
            "representational_bound": representational_bound,
        }
        if failed:
            status = "fail"
            message = f"structural field(s) did not survive the round trip: {sorted(failed)}."
        elif occ_warn:
            status = "warn"
            message = (
                f"occupancies drifted by up to {self._worst_occ:.3g} (above the warn bound "
                f"{eff.warn:.3g})."
            )
        else:
            status = "pass"
            message = f"{len(judged)} structural path(s) survived the round trip: {judged}."
        return CheckResult(
            check_id=CHECK_ID,
            status=status,
            paths=judged,
            measured=measured,
            tolerance_applied=applied if _OCC in judged else None,
            message=message,
        )
