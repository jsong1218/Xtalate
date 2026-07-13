"""Parse-time recovery orchestration (MASTER_SPEC Part 4 §3.3, parse-time scenarios).

Two catalog scenarios fire *before* a Canonical Object exists — the parser cannot even build one:

* ``missing_species`` — a VASP-4 POSCAR lists atom counts but no element symbols
  (``recovery_hint="supply_species"``); symbols are required (Part 2 §3.3).
* ``truncate_corrupt_tail`` — a trajectory's final frame is corrupt
  (``recovery_hint="truncate_at_last_valid_frame"``, Part 3 §5 rule 4).

These cannot be handled by ``RecoveryEngine.resolve`` (which rewrites an existing object). Instead
the parser exposes an optional ``parse_recover`` hook (Part 3 §2, additive to ``parse``): this
module tries the ordinary parse, and if it raises a *recoverable* ``ParseError`` whose hint maps to
a scenario the caller supplied a preset for, it re-parses through the hook and records one
``AppliedAssumption`` per applied choice. The resulting assumptions ride into ``ConversionEngine.
convert`` via its ``parse_recovery`` parameter and land in the Conversion Report exactly like a
pre-flight recovery would (**P4** — every fabrication or reduction is a recorded choice).

Layering (Part 1 §5.1): ``conversion`` sits above ``discovery``/``recovery``/``parsers``, so this
module may import the sniffer, the recovery result types, and drive parsers through the registry.
Without a matching preset — or with an explicit ``abort`` — the recoverable ``ParseError`` is
re-raised unchanged: refusal is the default (Part 4 §4), and a parse that produced no object is a
parse error, not a completed-but-refused conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO

from xtalate.capabilities import Registry
from xtalate.discovery import Sniffer
from xtalate.recovery import (
    AppliedAssumption,
    FrameDrop,
    RecoveryError,
    SuppliedField,
    available_options,
)
from xtalate.schema import CanonicalObject
from xtalate.sdk import ParseError, ParseIssue

# A recoverable parse hint (Part 3 §5) → the recovery scenario that resolves it (Part 4 §3.3).
_HINT_TO_SCENARIO = {
    "supply_species": "missing_species",
    "truncate_at_last_valid_frame": "truncate_corrupt_tail",
}


@dataclass
class ParseRecovery:
    """The outcome of a parse that may have applied a parse-time recovery. ``assumptions`` is empty
    for an ordinary (or cleanly-recovered) parse; ``issues`` carries the parse warnings, including
    the recovery's own (``POSCAR_SPECIES_SUPPLIED`` / ``XYZ_TRUNCATED``)."""

    canonical: CanonicalObject
    format_id: str
    assumptions: list[AppliedAssumption] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


def parse_with_recovery(
    registry: Registry,
    data: bytes,
    *,
    filename: str | None,
    format_override: str | None = None,
    recovery_choices: dict[str, dict[str, object]] | None = None,
) -> ParseRecovery:
    """Sniff + parse ``data``; if the parse raises a recoverable ``ParseError`` the caller supplied
    a preset for, re-parse through the parser's ``parse_recover`` hook and record the Assumption."""
    recovery_choices = recovery_choices or {}
    fmt = format_override or Sniffer(registry).sniff(data, filename).format_id
    if fmt is None:
        raise ParseError(
            [
                ParseIssue(
                    severity="error",
                    code="UNKNOWN_FORMAT",
                    message="could not determine the source format; pass --format to override",
                )
            ]
        )
    if fmt not in {p.format_id for p in registry.parsers()}:
        raise ParseError(
            [
                ParseIssue(
                    severity="error",
                    code="UNKNOWN_FORMAT",
                    message=f"no parser registered for format {fmt!r}",
                )
            ]
        )
    parser = registry.get_parser(fmt)
    try:
        result = parser.parse(BytesIO(data), filename=filename)
        return ParseRecovery(canonical=result.canonical, format_id=fmt, issues=list(result.issues))
    except ParseError as exc:
        recovered = _try_recover(parser, data, filename, fmt, exc, recovery_choices)
        if recovered is None:
            raise  # no preset, or an explicit abort — the recoverable error stands (Part 4 §4).
        return recovered


def _try_recover(
    parser: object,
    data: bytes,
    filename: str | None,
    fmt: str,
    error: ParseError,
    recovery_choices: dict[str, dict[str, object]],
) -> ParseRecovery | None:
    """Apply a parse-time preset if one matches the error's recovery hint; else return ``None``."""
    issue = next((i for i in error.issues if i.recovery_hint), None)
    if issue is None or issue.recovery_hint not in _HINT_TO_SCENARIO:
        return None
    scenario = _HINT_TO_SCENARIO[issue.recovery_hint]
    choice_spec = recovery_choices.get(scenario)
    if choice_spec is None:
        return None  # no preset for this scenario → refuse (the parse error stands).
    code = choice_spec.get("choice")
    offered = available_options(scenario)
    if not isinstance(code, str) or code not in offered:
        raise RecoveryError(f"{scenario!r}: choice {code!r} is not an offered option {offered!r}")
    if scenario == "truncate_corrupt_tail" and code == "abort":
        return None  # abort is an explicit give-up: the recoverable parse error stands.

    raw_params = choice_spec.get("parameters")
    parameters: dict[str, object] = raw_params if isinstance(raw_params, dict) else {}
    result = parser.parse_recover(  # type: ignore[attr-defined]
        BytesIO(data),
        filename=filename,
        hint=issue.recovery_hint,
        choice=code,
        parameters=parameters,
    )
    assumption = _build_assumption(scenario, code, parameters, result.canonical, issue)
    return ParseRecovery(
        canonical=result.canonical,
        format_id=fmt,
        assumptions=[assumption],
        issues=list(result.issues),
    )


def _build_assumption(
    scenario: str,
    code: str,
    parameters: dict[str, object],
    canonical: CanonicalObject,
    issue: ParseIssue,
) -> AppliedAssumption:
    """Construct the recorded Assumption for a parse-time recovery. Its id is provisional (``A1``);
    ``ConversionEngine.convert`` renumbers all assumptions in application order (parse-time first).
    """
    if scenario == "missing_species":
        # Fabricative: symbols did not exist in the source file (Part 4 §3.1). Recorded with a
        # `supplied` field so the Conversion Report marks atoms.symbols as fabricated, not carried.
        return AppliedAssumption(
            id="A1",
            scenario=scenario,
            choice=code,
            parameters=_species_params(code, parameters),
            origin="preset",
            description=(
                f"Element symbols supplied at parse time via {code!r}; the source (VASP-4 POSCAR) "
                "listed only atom counts. Symbols are required to represent the structure and did "
                "not exist in the file — they are fabricated by this recorded choice, not carried."
            ),
            supplied=[
                SuppliedField(
                    path="atoms.symbols",
                    detail="Element symbols supplied by recovery — absent from the source file.",
                )
            ],
        )
    # truncate_corrupt_tail — selective reductive: genuine frames kept, corrupt tail dropped.
    kept = canonical.frame_count
    return AppliedAssumption(
        id="A1",
        scenario=scenario,
        choice=code,
        parameters={"kept_frames": kept, "corrupt_parse_issue": issue.code},
        origin="preset",
        description=(
            f"Kept frames 0..{kept - 1} and discarded the corrupt tail at frame {kept} "
            f"({issue.code}: {issue.message}). Which frames survive is genuine source data, so it "
            "is a recorded selective reduction, not a fabrication."
        ),
        removed=[
            FrameDrop(
                path="atoms.positions",
                reason="Source trajectory has a corrupt final frame; the valid prefix is kept.",
                detail=f"{kept} valid frame(s) retained; the corrupt tail was discarded per A1.",
            )
        ],
    )


def _species_params(code: str, parameters: dict[str, object]) -> dict[str, object]:
    """Report parameters for a ``missing_species`` Assumption, keyed by choice."""
    if code == "species_map":
        return {"species": parameters.get("species")}
    return {"source": "upload_reference"}
