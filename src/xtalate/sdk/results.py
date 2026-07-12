"""Parse results and the error contract (MASTER_SPEC Part 3 §5).

Every parser shares one result/error shape so the Discovery Engine, Conversion Engine, and
API handle malformed files uniformly. The load-bearing rule (§5 rule 1): **warnings
accompany success; errors preclude it.** There is no "best-effort object plus errors"
middle state — a half-parsed structure presented as data is silent loss (P1).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from xtalate.schema import CanonicalObject


class ParseIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["warning", "error"]
    code: str  # Stable machine code, e.g. "XYZ_INCONSISTENT_ATOM_COUNT".
    message: str  # Human-readable, specific: what, where, why it matters.
    location: str | None = None  # e.g. "line 4192", "frame 17", "data block 2".
    # Machine-consumable hint the Recovery Engine can act on, e.g. "supply_species".
    recovery_hint: str | None = None


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical: CanonicalObject  # Present iff parse succeeded (possibly with warnings).
    issues: list[ParseIssue] = Field(default_factory=list)  # Warnings; empty for a clean parse.


class ParseError(Exception):
    """Raised when no valid CanonicalObject can be produced (§5). Carries ``issues`` with
    at least one error-severity entry."""

    def __init__(self, issues: list[ParseIssue], message: str | None = None) -> None:
        errors = [i for i in issues if i.severity == "error"]
        if not errors:
            raise ValueError("ParseError requires at least one error-severity ParseIssue")
        self.issues = issues
        super().__init__(message or errors[0].message)
