"""`ambiguous_units` recovery scenario tests (v1.3 M46-S1, MASTER_SPEC Part 4 §3.3).

The parse-time-blocking scenario that opens v1.3: a LAMMPS file that does not declare
its unit style cannot be converted to canonical Å/fs/eV at all, so the parser raises a
recoverable ``ambiguous_units``-hinted ``ParseError`` and the conversion refuses until
the caller names a style. The scenario mirrors `ambiguous_stress_convention` (M40) on
the two load-bearing axes: classified **FABRICATIVE** for mode gating (an explicit
choice is required in both strict and permissive modes — no auto-applied default, R3)
and listed in **INTERPRETIVE_SCENARIOS** (the raw numbers are genuine source data; only
their scale is resolved, so no ``supplied`` entry is ever recorded).

S1 has no LAMMPS parser yet (that is S2), so the refuse/resolve pair is exercised
through the real public seam — ``conversion.parse_with_recovery`` — with a minimal stub
parser that raises the recoverable issue the dump parser will raise, and applies the
chosen style in ``parse_recover`` exactly as the real one will.
"""

from __future__ import annotations

from typing import BinaryIO

import pytest

from tests._dummy_plugins import make_object
from xtalate.capabilities import Registry
from xtalate.conversion import parse_with_recovery
from xtalate.parsers._lammps import UNIT_STYLES
from xtalate.recovery import RecoveryError
from xtalate.recovery.scenarios import (
    INTERPRETIVE_SCENARIOS,
    SCENARIO_HAZARD,
    HazardClass,
    available_options,
    is_interpretive,
)
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

STYLE = "ambiguous_units"
_HINT = "ambiguous_units"


class _AmbiguousUnitsStubParser(ParserPlugin):
    """The S2 dump parser's shape, stubbed: ``parse`` raises the recoverable
    ``ambiguous_units`` issue; ``parse_recover`` applies the chosen style and returns a
    minimal object (the real parser re-reads the file with the style's conversion
    factors — the mechanical detail S2 owns, not this scenario's contract)."""

    format_id = "stub_lammps"
    format_name = "Stub LAMMPS"
    version = "0.1.0"

    def sniff(self, head: bytes, filename: str | None) -> float:
        return 0.95 if head.startswith(b"ITEM: TIMESTEP") else 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        raise ParseError(
            [
                ParseIssue(
                    severity="error",
                    code="STUB_AMBIGUOUS_UNITS",
                    message="no unit style declared; every position, velocity, and box "
                    "bound is uninterpretable until the style is known",
                    recovery_hint=_HINT,
                )
            ]
        )

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
    ) -> ParseResult:
        assert hint == _HINT
        return ParseResult(
            canonical=make_object(self.format_id),
            issues=[
                ParseIssue(
                    severity="warning",
                    code="STUB_UNITS_INTERPRETED",
                    message=f"interpreted units as {choice}",
                )
            ],
        )

    def capabilities(self) -> FormatCapabilities:
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="read",
            fields={"atoms.positions": FieldCapability(level=CapabilityLevel.FULL)},
            native_coordinate_system="cartesian",
        )


def _registry() -> Registry:
    reg = Registry()
    reg.register_parser(_AmbiguousUnitsStubParser())
    return reg


# --- registration (mirrors the ambiguous_stress_convention rows) ---------------------


def test_registered_fabricative_and_interpretive() -> None:
    assert SCENARIO_HAZARD[STYLE] is HazardClass.FABRICATIVE
    assert STYLE in INTERPRETIVE_SCENARIOS
    assert is_interpretive(STYLE)


def test_options_are_exactly_metal_real_si() -> None:
    # The option list starts at exactly these three and grows only by golden-corpus
    # evidence (M49), never speculatively from LAMMPS's documented style list.
    assert available_options(STYLE) == ["metal", "real", "si"]


def test_unknown_style_is_not_offered() -> None:
    # A style beyond the three is not an ambiguity to resolve — the catalog cannot
    # interpret it — so naming one must refuse (never offered-then-refused, Part 4 §3.3).
    assert "lj" not in available_options(STYLE)


# --- no preset ⇒ no parse (the R3 refusal) -------------------------------------------


def test_without_a_preset_the_recoverable_parse_error_stands() -> None:
    with pytest.raises(ParseError) as excinfo:
        parse_with_recovery(_registry(), b"ITEM: TIMESTEP\n0\n", filename="x.dump")
    (issue,) = excinfo.value.issues
    assert issue.recovery_hint == _HINT
    # The refusal names the scenario so the CLI can point the user at
    # `--recover ambiguous_units=metal` — the actionable hint, never a dead end.
    assert "unit style" in issue.message


# --- with a preset ⇒ resolves, Assumption recorded, interpretation stated -------------


@pytest.mark.parametrize("style", ["metal", "real", "si"])
def test_resolves_with_an_assumption_recording_the_interpretation(style: str) -> None:
    result = parse_with_recovery(
        _registry(),
        b"ITEM: TIMESTEP\n0\n",
        filename="x.dump",
        recovery_choices={STYLE: {"choice": style}},
    )
    assert result.format_id == "stub_lammps"
    (assumption,) = result.assumptions
    assert assumption.scenario == STYLE
    assert assumption.choice == style
    assert assumption.parameters == {"unit_style": style}
    # Plain language, naming the applied interpretation (Part 4 §2) — the report states
    # which basis every position/velocity/box bound was converted from.
    assert f"Interpreted LAMMPS units as `{style}`" in assumption.description
    assert "converted from that basis" in assumption.description
    # Interpretive: the values are genuine source data, so nothing is filed `supplied`.
    assert assumption.supplied == []
    # The recovery's own warning echoes into the report (Part 3 §5 rule 5), never silent.
    assert [i.code for i in result.issues] == ["STUB_UNITS_INTERPRETED"]


def test_assumption_unit_summaries_match_the_shared_unit_tables() -> None:
    """The plain-language summaries in the Assumption are the same strings the shared
    `_lammps` unit tables carry (the recovery layer restates them without importing
    parsers; this pins the two to one vocabulary)."""
    for style in ["metal", "real", "si"]:
        result = parse_with_recovery(
            _registry(),
            b"ITEM: TIMESTEP\n0\n",
            filename="x.dump",
            recovery_choices={STYLE: {"choice": style}},
        )
        (assumption,) = result.assumptions
        assert UNIT_STYLES[style].summary in assumption.description


# --- an invalid choice is a caller error, not a refusal -------------------------------


def test_unoffered_choice_is_rejected() -> None:
    with pytest.raises(RecoveryError, match="not an offered option"):
        parse_with_recovery(
            _registry(),
            b"ITEM: TIMESTEP\n0\n",
            filename="x.dump",
            recovery_choices={STYLE: {"choice": "lj"}},
        )
