"""The ``RepairOperation`` contract and its plain result types (v1.7 M64; D249).

A repair operation is a **pure, deterministic** function
``(CanonicalObject, recorded parameters) → CanonicalObject`` with fully serializable
parameters — the property that makes every repair reproducible from its Conversion Report alone.
Operations never read config/global state, never draw randomness, and never mutate their input
(they return new objects via ``model_copy``); the Conversion Engine applies an **ordered** list
between parse and pre-flight and records the order.

This module holds only the contract and result shapes. The concrete operations live in
``repair.operations``; the ordered application lives in ``repair.engine``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from xtalate.schema import CanonicalObject

#: The recovery scenario a repair-blocked-for-a-cell resolves through. Restated here (rather than
#: imported from ``recovery.scenarios``) because ``repair`` sits beside ``recovery`` and may not
#: import it (layering; D249); the value is the registered ``missing_lattice`` scenario code — a
#: test asserts this constant stays in lockstep with ``SCENARIO_HAZARD`` so it can never drift.
REPAIR_BLOCK_MISSING_LATTICE = "missing_lattice"

#: The **transformative** hazard class — Part 4 §3.1's fourth class (v1.7 M64; D251). Wrap (and,
#: in M65, center) fit none of the recovery taxonomy's three classes: they neither remove nor
#: fabricate — they transform values in place, losing the originals. The class carries the same
#: consent discipline as reductive loss: explicit request **plus** a report warning naming exactly
#: what is unrecoverable (the operation's ``hazards``). It is a repair-side class, not a recovery
#: ``SCENARIO_HAZARD`` entry — no *scenario* is transformative (repairs are not recovery
#: scenarios); an operation declares ``hazard_class``.
TRANSFORMATIVE_HAZARD = "transformative"

#: The **selective-reductive** hazard class — recovery's own vocabulary, reused by repair
#: (D254): deduplicate removes real atoms (a reductive loss), so it draws the same class
#: recovery's ``frame_selection`` uses, with ``transformative`` (D251) the single
#: repair-side addition. Restated here rather than imported from ``recovery.scenarios``
#: because ``repair`` depends on ``schema`` + ``sdk`` only (D249's layering); a test
#: asserts this stays in lockstep with ``HazardClass.SELECTIVE_REDUCTIVE`` so the shared
#: vocabulary can never drift.
SELECTIVE_REDUCTIVE_HAZARD = "selective_reductive"


class RepairError(ValueError):
    """A repair *request* that is incoherent — a caller error, not a conversion refusal.

    Mirrors ``RecoveryError``: the caller asked for something that cannot be done as asked
    (an unknown operation name, non-JSON-serializable parameters, parameters an operation does
    not take, or an operation that cannot act on this object *and* has no recovery-composable
    route). Distinct from a *blocked* repair, which is a legitimate conversion outcome the
    engine routes through the existing recovery machinery (see ``RepairBlock``).
    """


@dataclass(frozen=True)
class RepairHazard:
    """One plain-language hazard statement naming what a repair makes unrecoverable.

    Rendered as a ``ReportWarning(source="repair")`` row in the Conversion Report, so the
    destructive half of a repair (D251's *transformative* hazard class) is stated like any other
    loss — never glossed.
    """

    code: str  # Stable machine code, e.g. "WRAP_DISCARDS_UNWRAPPED_PATHS".
    message: str  # Plain language naming exactly what is unrecoverable.


@dataclass(frozen=True)
class RepairBlock:
    """A requested repair that cannot run against *this* object.

    All-or-nothing: one blocked operation blocks the whole requested set — a half-repaired
    structure presented as complete would be the silent failure this engine exists to prevent.
    ``reason`` names the recovery machinery the block resolves through (``repair.contract``
    restates ``missing_lattice`` for the cell-less case; the Conversion Engine maps it onto the
    existing scenario with the pair-specific options). Nothing is ever fabricated to un-block a
    repair (D43).
    """

    operation: str  # The operation that cannot run, e.g. "wrap_into_cell".
    reason: str  # Stable machine reason, e.g. REPAIR_BLOCK_MISSING_LATTICE.
    path: str | None  # Canonical field path implicated, e.g. "cell.lattice_vectors".
    detail: str  # Plain language: what is missing and what the caller can do.


@dataclass
class AppliedRepair:
    """One applied repair, plus the record the D249 triple needs (mapped by the engine).

    ``id`` is the report ``Assumption`` id (``"A1"`` …) the Conversion Engine assigns when it
    numbers every applied record in application order. ``parameters`` are the complete, recorded
    parameters of this application — the reproducibility harness re-derives the repaired object
    from exactly these. ``description`` is the plain-language statement of what changed;
    ``hazards`` the transformative-loss statements for the report's ``warnings``.
    """

    id: str  # Report assumption id, assigned by the Conversion Engine.
    operation: str  # Operation machine name, e.g. "wrap_into_cell".
    parameters: dict[str, Any]  # Complete parameters of this application (JSON-serializable).
    description: str  # Plain-language statement of what changed.
    hazards: list[RepairHazard] = field(default_factory=list)


@dataclass
class RepairOutcome:
    """Outcome of ``apply_repairs``. ``canonical`` is ``None`` iff a requested operation blocked
    (in which case ``blocked`` names the first blocker and **no** operation was applied)."""

    canonical: CanonicalObject | None
    applied: list[AppliedRepair] = field(default_factory=list)
    blocked: list[RepairBlock] = field(default_factory=list)


@dataclass(frozen=True)
class RepairRequest:
    """One user-requested repair: an operation name and its complete parameters."""

    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)


class RepairOperation(ABC):
    """A registered repair operation (D249): pure, deterministic, self-describing.

    Subclasses declare their machine ``operation`` name (the registry key, unique across the
    closed set) and implement ``apply`` (the pure transform), ``block`` (an honest refusal when
    the transform cannot run against the given object — default: never blocks), and
    ``describe`` (the plain-language "what changed" statement for the report). ``hazards``
    carries the transformative-loss statements (D251) that accompany every application;
    ``recorded_parameters`` (the complete parameters of a specific application, for
    reproducibility, D252) and ``hazards_for`` (per-application hazards) default to the
    verbatim request parameters and the class ``hazards`` tuple respectively.
    """

    operation: ClassVar[str] = ""
    hazards: ClassVar[tuple[RepairHazard, ...]] = ()
    #: The operation's hazard class (D251): "transformative" for an operation that changes values
    #: in place and loses the originals (wrap, center); None for a reference/non-destructive op.
    hazard_class: ClassVar[str | None] = None

    def block(self, obj: CanonicalObject, parameters: dict[str, Any]) -> RepairBlock | None:
        """Return a ``RepairBlock`` if this operation cannot run against ``obj``, else ``None``.

        A block is a *legitimate refusal* routed through existing recovery machinery (e.g. a
        cell-less wrap resolves through ``missing_lattice``) — never a raised error and never a
        fabricated workaround.
        """
        return None

    @abstractmethod
    def apply(self, obj: CanonicalObject, parameters: dict[str, Any]) -> CanonicalObject:
        """Apply the operation to ``obj`` and return the repaired object.

        Pure and deterministic: must not mutate ``obj`` (return a new object via
        ``model_copy``), must not read config/global state, and must not draw randomness.
        ``parameters`` are the recorded parameters of this application.
        """

    def recorded_parameters(
        self, obj: CanonicalObject, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """The complete parameters of *this application*, as recorded in the report.

        Default: the request's parameters verbatim — an operation that consumes exactly
        what was requested records exactly that (M64's identity/wrap records are
        unchanged). An operation that *computes* a deterministic parameter from the
        object (M65-S1: ``species_reorder``'s permutation map) returns the record that
        re-derivation must replay: the reproducibility contract is that ``apply`` is a
        pure function of ``(obj, recorded_parameters)``.
        """
        return parameters

    def hazards_for(self, obj: CanonicalObject, parameters: dict[str, Any]) -> list[RepairHazard]:
        """The hazard statements of *this application*, in application order.

        Default: the class-level ``hazards`` tuple verbatim — a transformative operation
        states its loss on every application (D251). An operation whose statement is
        conditional (M65-S1: ``species_reorder``'s order-changed advisory, which would
        lie if fired when the permutation is the identity) overrides this.
        """
        return list(self.hazards)

    @abstractmethod
    def describe(self, obj: CanonicalObject, parameters: dict[str, Any]) -> str:
        """The plain-language statement of what this application changed (recorded verbatim)."""
