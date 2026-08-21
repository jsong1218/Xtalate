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

import inspect
from dataclasses import dataclass, field
from io import BytesIO
from typing import cast

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
from xtalate.sdk import ParseError, ParseIssue, ParseResult, enforce_max_frames

# A recoverable parse hint (Part 3 §5) → the recovery scenario that resolves it (Part 4 §3.3).
_HINT_TO_SCENARIO = {
    "supply_species": "missing_species",
    "truncate_at_last_valid_frame": "truncate_corrupt_tail",
    # M46: a LAMMPS file that declares no unit style cannot be converted to canonical
    # Å/fs/eV at all — parse-time-blocking, so it fires from the parser like the other two
    # parse-time scenarios. The scenario code equals the hint code (the `ambiguous_units`
    # catalog entry); the parser's `parse_recover` applies the chosen style's conversion
    # factors on re-read.
    "ambiguous_units": "ambiguous_units",
    # M48: a LAMMPS *data* file whose ``Atoms`` section carries no ``# <style>`` comment cannot
    # be read at all — the column layout (which column is the charge, which the molecule-id) is
    # unknowable — so it is parse-time-blocking and fires from the parser like the others. The
    # scenario code equals the hint code (the `ambiguous_atom_style` catalog entry); a data file
    # also declares neither units nor element symbols, so this hint typically resolves *alongside*
    # `ambiguous_units` + `missing_species` in the compound recovery loop below.
    "ambiguous_atom_style": "ambiguous_atom_style",
}

#: The parse-time recovery scenarios, in resolution-stage order (Part 4 §3.3). These resolve *ahead*
#: of any conversion-time scenario, since they fire while the source is still parsed — so a pause
#: mixing a parse-time scenario with a conversion-time one must render the parse-time card first.
#: Derived from ``_HINT_TO_SCENARIO`` (single source, deduplicated, insertion-ordered) so the names
#: are never re-typed; ``backend.vocabulary`` prepends this to the engine's conversion-time
#: ``_DEP_ORDER`` to publish one resolution order the Web UI consumes (v0.7 review, F4). Since M48 a
#: single parse can fire *several* of these at once (a LAMMPS data file needs ``ambiguous_units`` +
#: ``missing_species`` + ``ambiguous_atom_style`` together), so this fixed order also pins how such
#: co-occurring parse-time cards are rendered and how their Assumptions are numbered.
PARSE_TIME_SCENARIOS: tuple[str, ...] = tuple(dict.fromkeys(_HINT_TO_SCENARIO.values()))


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
    max_frames: int | None = None,
) -> ParseRecovery:
    """Sniff + parse ``data``; if the parse raises a recoverable ``ParseError`` the caller supplied
    a preset for, re-parse through the parser's ``parse_recover`` hook and record the Assumption.

    ``max_frames`` (optional; the HTTP service passes its ``settings.max_frames``) makes the frame
    cap a real gate (M39-S3, F1): the trajectory's frames are counted as they stream **before** the
    materialized parse, and an over-cap file is refused with ``FrameLimitExceeded`` without ever
    building the whole object — the cap bounds worker memory, which is its entire point."""
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
    if max_frames is not None:
        enforce_max_frames(parser, data, filename=filename, max_frames=max_frames)
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
    """Apply parse-time presets in an accumulating loop (M48); return ``None`` to refuse.

    A single file can lack several required facts at once — a LAMMPS *data* file declares neither
    its unit style nor its element symbols (nor its atom style, when the ``Atoms`` comment is
    absent) — so recovery is a fixpoint, not a single step: re-parse with every choice resolved so
    far, and if that surfaces a *new* recoverable need the caller supplied a preset for, resolve it
    too and re-parse again. One ``Assumption`` is recorded per need that actually fired, in the
    order they surfaced (never for an unused supplied preset — the loop only ever touches a need the
    parser genuinely raised, so the report stays honest, P1). The accumulated choices ride into each
    re-read via ``parse_recover``'s ``recovery_context`` (the M48 SDK seam).

    Refusal is the default (Part 4 §4): ``None`` is returned when the *first* need has no preset or
    is an explicit ``abort`` — the recoverable parse error stands unchanged. Once any recovery has
    been applied, a later unmet need is an honest blocker whose ``ParseError`` propagates (the parse
    genuinely cannot complete), never a silent drop of the progress made.
    """
    context: dict[str, dict[str, object]] = {}
    resolved: list[tuple[str, str, dict[str, object], ParseIssue]] = []
    current = error
    while True:
        issue = next((i for i in current.issues if i.recovery_hint), None)
        if issue is None or issue.recovery_hint not in _HINT_TO_SCENARIO:
            # No further recoverable need. With recoveries already applied, reaching here means the
            # latest re-read raised a *non-recoverable* error — an honest blocker; propagate it.
            if resolved:
                raise current
            return None
        scenario = _HINT_TO_SCENARIO[issue.recovery_hint]
        if scenario in context:
            # The parser re-raised a need already resolved → no progress; surface it, never loop.
            raise current
        choice_spec = recovery_choices.get(scenario)
        if choice_spec is None:
            if resolved:
                raise current  # partial progress, this need unmet → honest blocker (never silent).
            return None  # first need has no preset → refuse (the parse error stands, Part 4 §4).
        code = choice_spec.get("choice")
        offered = available_options(scenario)
        if not isinstance(code, str) or code not in offered:
            raise RecoveryError(
                f"{scenario!r}: choice {code!r} is not an offered option {offered!r}"
            )
        if scenario == "truncate_corrupt_tail" and code == "abort":
            if resolved:
                raise current
            return None  # abort is an explicit give-up: the recoverable parse error stands.

        raw_params = choice_spec.get("parameters")
        parameters: dict[str, object] = raw_params if isinstance(raw_params, dict) else {}
        context[scenario] = {"choice": code, "parameters": parameters}
        resolved.append((scenario, code, parameters, issue))
        try:
            result = _invoke_parse_recover(
                parser,
                BytesIO(data),
                filename=filename,
                hint=issue.recovery_hint,
                choice=code,
                parameters=parameters,
                recovery_context=dict(context),
            )
        except ParseError as exc:
            current = exc  # a further parse-time need surfaced under the applied choice(s); loop.
            continue
        assumptions = [_build_assumption(s, c, p, result.canonical, i) for (s, c, p, i) in resolved]
        return ParseRecovery(
            canonical=result.canonical,
            format_id=fmt,
            assumptions=assumptions,
            issues=list(result.issues),
        )


def _invoke_parse_recover(
    parser: object,
    stream: BytesIO,
    *,
    filename: str | None,
    hint: str,
    choice: str,
    parameters: dict[str, object],
    recovery_context: dict[str, dict[str, object]],
) -> ParseResult:
    """Call ``parser.parse_recover``, threading ``recovery_context`` only when the override accepts
    it. The M48 seam is additive with a default on the ABC, so first-party parsers (and any plugin
    written against the current SDK) take the keyword; a third-party parser overriding the older
    signature — one that never needed compound recovery — is called without it and keeps working
    (P6, no plugin break)."""
    recover = parser.parse_recover  # type: ignore[attr-defined]
    if "recovery_context" in inspect.signature(recover).parameters:
        return cast(
            ParseResult,
            recover(
                stream,
                filename=filename,
                hint=hint,
                choice=choice,
                parameters=parameters,
                recovery_context=recovery_context,
            ),
        )
    return cast(
        ParseResult,
        recover(stream, filename=filename, hint=hint, choice=choice, parameters=parameters),
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
                f"Element symbols supplied at parse time via {code!r}; the source file carried no "
                "element symbols (a VASP-4 POSCAR lists only atom counts; a LAMMPS dump lists "
                "only numeric atom types). Symbols are required to represent the structure and "
                "did not exist in the file — they are fabricated by this recorded choice, not "
                "carried."
            ),
            supplied=[
                SuppliedField(
                    path="atoms.symbols",
                    detail="Element symbols supplied by recovery — absent from the source file.",
                )
            ],
        )
    if scenario == "ambiguous_units":
        # Interpretive (Part 4 §3.1, M46): the file's raw numbers are genuine source data —
        # only their unit *scale* was unresolved. No `supplied` entry: nothing was created;
        # the Assumption's plain-language description states the interpretation applied, so
        # the Conversion Report says which basis every position/velocity/box bound was
        # converted from (a wrong choice silently rescales every value — hence the P4
        # refusal discipline, never a guessed default).
        return AppliedAssumption(
            id="A1",
            scenario=scenario,
            choice=code,
            parameters={"unit_style": code},
            origin="preset",
            description=(
                f"Interpreted LAMMPS units as `{code}` ({_UNIT_STYLE_SUMMARIES[code]}); all "
                "positions, velocities, and box bounds converted from that basis. The source "
                "file declared no unit style — the values are genuine source data, only their "
                "scale was resolved by this recorded choice, never guessed."
            ),
        )
    if scenario == "ambiguous_atom_style":
        # Interpretive (Part 4 §3.1, M48): the data file's `Atoms` columns are genuine source
        # data — the atom style only fixes *how to read the columns already present* (which is the
        # charge, which the molecule-id), fabricating nothing. No `supplied` entry: nothing was
        # created; the description states the layout applied, so the Conversion Report says which
        # column each value was read from (a wrong choice silently misreads charges as molecule-ids
        # — hence the P4 refusal discipline, never a guessed default).
        return AppliedAssumption(
            id="A1",
            scenario=scenario,
            choice=code,
            parameters={"atom_style": code},
            origin="preset",
            description=(
                f"Interpreted the LAMMPS data `Atoms` columns as atom style `{code}` "
                f"({_ATOM_STYLE_SUMMARIES[code]}); the source file's `Atoms` section carried no "
                "`# <style>` comment naming the layout. The columns are genuine source data — only "
                "their meaning was resolved by this recorded choice, never guessed."
            ),
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


#: The human-readable unit basis per `ambiguous_units` choice, stated in the Assumption
#: description (the same summaries the shared `_lammps` unit tables carry; the recovery
#: layer does not import parsers, so the three labels are restated here and pinned by the
#: recovery test against the tables' own summaries).
_UNIT_STYLE_SUMMARIES = {
    "metal": "Å, ps, eV",
    "real": "Å, fs, kcal/mol",
    "si": "m, s, J",
}

#: The human-readable ``Atoms`` column layout per `ambiguous_atom_style` choice, stated in the
#: Assumption description (M48). The recovery layer does not import parsers, so the three layouts
#: are restated here and pinned by the recovery test against the data parser's own definitions.
_ATOM_STYLE_SUMMARIES = {
    "atomic": "id type x y z",
    "charge": "id type q x y z",
    "full": "id molecule-id type q x y z",
}
