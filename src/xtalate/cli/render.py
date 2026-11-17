"""Human-readable terminal renderers for the report schemas (MASTER_SPEC Appendix A, Part 3 §6.3).

Pure functions: report model in, plain-text string out. The CLI is a *thin presenter* (Part 1 §2)
— these renderers add no scientific logic and invent no information the reports do not already
carry; `--json` bypasses them entirely and emits the pydantic models verbatim. ASCII glyphs keep
the output legible in any terminal/pipe (✓/✗ are the one concession, matching the §6.3 inventory).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import JsonValue

from xtalate.conversion.batch import BatchReport
from xtalate.conversion.engine import DryRun
from xtalate.conversion.report import ConversionReport
from xtalate.discovery.report import DiscoveryReport
from xtalate.recovery.scenarios import describe_choice, describe_scenario
from xtalate.sdk import CapabilityLevel, FormatCapabilities
from xtalate.validation.report import ValidationReport

_PRESENCE = {"present": "✓", "absent": "✗", "mixed": "◐"}
_CAP = {
    CapabilityLevel.FULL: "full",
    CapabilityLevel.PARTIAL: "partial",
    CapabilityLevel.NONE: "none",
}
_CHECK = {"pass": "✓", "warn": "⚠", "fail": "✗", "skipped": "–"}


def render_discovery(report: DiscoveryReport) -> str:
    fmt = report.format
    lines = [
        f"File:   {report.file.get('filename')}  ({report.file.get('size_bytes')} bytes)",
        f"Format: {fmt.get('format_name')} [{fmt.get('format_id')}]  "
        f"confidence {fmt.get('confidence')}"
        + ("  (overridden)" if fmt.get("overridden") else "")
        + ("  (ambiguous)" if fmt.get("ambiguous") else ""),
    ]
    struct = report.structure
    lines.append(
        f"Structure: {struct.get('frame_count')} frame(s) × {struct.get('atom_count')} atoms; "
        f"species {', '.join(struct.get('species', []))}"
    )
    lines.append("")
    lines.append("Canonical fields (✓ present / ✗ absent / ◐ mixed · read capability):")
    for field in report.fields:
        glyph = _PRESENCE.get(field.status, "?")
        cap = _CAP.get(field.format_capability, str(field.format_capability))
        detail = f"  — {field.detail}" if field.detail else ""
        frames = (
            f"  frames {field.present_frames}"
            if field.status == "mixed" and field.present_frames is not None
            else ""
        )
        lines.append(f"  {glyph} {field.path:<32} [{cap}]{detail}{frames}")
    if report.extras:
        lines.append("")
        lines.append("Carried-through extras (namespaced, format-specific):")
        lines.extend(f"  + {key}" for key in report.extras)
    if report.issues:
        lines.append("")
        lines.append("Parse issues:")
        lines.extend(f"  ! [{i.severity}] {i.code}: {i.message}" for i in report.issues)
    return "\n".join(lines)


def render_conversion(report: ConversionReport) -> str:
    lines = [
        f"Conversion Report  [{report.stage} · {report.status} · {report.mode}]",
        f"  {report.source.get('format_id')} → {report.target.get('format_id')}",
    ]
    if report.status == "refused" and report.refusal is not None:
        lines.append(f"  REFUSED [{report.refusal.get('code')}]: {report.refusal.get('message')}")
        for scenario in report.refusal.get("unresolved_scenarios", []):
            lines.append(f"    · {scenario.get('scenario')}: {scenario.get('detail')}")
    lines.append(f"  preserved ({len(report.preserved)}):")
    for entry in report.preserved:
        lines.append(f"    ✓ {entry.path}" + (f"  — {entry.detail}" if entry.detail else ""))
    lines.append(f"  removed ({len(report.removed)}):")
    for removed in report.removed:
        lines.append(f"    ✗ {removed.path}  — {removed.reason}")
    if report.supplied:
        lines.append(f"  supplied ({len(report.supplied)}):")
        for sup in report.supplied:
            lines.append(f"    + {sup.path}  (from {sup.from_assumption})")
    if report.assumptions:
        lines.append(f"  assumptions ({len(report.assumptions)}):")
        for a in report.assumptions:
            lines.append(f"    ~ {a.id} {a.scenario}={a.choice}: {a.description}")
    if report.warnings:
        lines.append(f"  warnings ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    ⚠ [{w.source}] {w.message}")
    return "\n".join(lines)


def render_validation(report: ValidationReport) -> str:
    profile = report.tolerance_profile.get("name", "?")
    lines = [f"Validation Report  [{report.status}]  (tolerance profile: {profile})"]
    for check in report.checks:
        lines.append(f"  {_CHECK.get(check.status, '?')} {check.check_id}: {check.message}")
    if report.reparse_issues:
        lines.append("  re-parse issues:")
        lines.extend(f"    ! [{i.severity}] {i.code}: {i.message}" for i in report.reparse_issues)
    return "\n".join(lines)


def render_batch(report: BatchReport) -> str:
    """The batch report's human rendering — a **view** of the model, never a second schema.

    One summary line per file (path → outcome, linking by path to the embedded per-file
    ConversionReport/ValidationReport sections), then the tallies. It computes **nothing the
    model does not already hold**: a rendering that digested per-file content (top losses,
    merged assumptions) would be the second-report-schema defect the roadmap names (§6)."""
    lines = [
        f"Batch Report  [{report.tallies.converted} converted · "
        f"{report.tallies.refused} refused · {report.tallies.failed} failed]",
        f"  target: {report.manifest.target}  ({report.manifest.output_mode})",
    ]
    for entry in report.entries:
        if entry.status == "converted":
            status = entry.validation.status if entry.validation is not None else "converted"
            lines.append(f"  ✓ {entry.source}  converted [{status}]")
        elif entry.status == "refused":
            code = ""
            if entry.conversion is not None and entry.conversion.refusal is not None:
                code = entry.conversion.refusal.get("code", "")
            lines.append(f"  ✗ {entry.source}  refused [{code}]")
        else:
            code = entry.error.code if entry.error is not None else ""
            message = entry.error.message if entry.error is not None else ""
            lines.append(f"  ✗ {entry.source}  failed [{code}]: {message}")
    labels = report.tallies.label_presence
    lines.append(
        f"  labels: {labels.energy} energy · {labels.forces} forces · {labels.stress} stress"
    )
    if report.note:
        lines.append(f"  note: {report.note}")
    return "\n".join(lines)


def render_analysis(plugin_name: str, plugin_version: str, results: Mapping[str, JsonValue]) -> str:
    """Render one analysis plugin's namespaced results as a labelled table (v1.8 M70).

    A **view** of what the plugin wrote, never a second schema: one ``key = value`` line per
    entry, sorted by key so the output is deterministic. A ``null`` value is shown as ``null`` and
    the plugin's paired plain-language sibling (a ``composition:density_note`` beside a null
    ``composition:mass_density_g_per_cm3``) renders on its own line — the honest statement of an
    absence travels with the absence (P1, P3), never a silently dropped ``None``. Scalars render
    bare; lists and objects render as compact JSON so a structured result (an RDF curve, a table)
    stays legible. ``--json`` bypasses this and emits ``{plugin, version, results}`` verbatim.
    """
    lines = [
        f"Analysis Report  [{plugin_name} {plugin_version}]",
        f"  results ({len(results)}):",
    ]
    for key in sorted(results):
        value = results[key]
        rendered = "null" if value is None else json.dumps(value, ensure_ascii=False)
        lines.append(f"    {key} = {rendered}")
    return "\n".join(lines)


def render_capabilities(declarations: dict[str, dict[str, FormatCapabilities]]) -> str:
    lines: list[str] = []
    for format_id in sorted(declarations):
        directions = declarations[format_id]
        any_caps = next(iter(directions.values()))
        lines.append(f"{any_caps.format_name} [{format_id}]")
        for direction in ("read", "write"):
            caps = directions.get(direction)
            if caps is None:
                # A parser-only format (a read row, no write row — D159) has an honest
                # one-line statement, not a bare "not registered" that implies the side
                # merely went unregistered: it declares a read side and no write side
                # exists, so it is never a conversion target. (The symmetric write-only
                # case is not produced by any current format but renders plainly.)
                if direction == "write" and "read" in directions:
                    lines.append(
                        "  write: (not registered — read-only/parser-only format; "
                        "never a conversion target)"
                    )
                else:
                    lines.append(f"  {direction}: (not registered)")
                continue
            frames = "unlimited" if caps.max_frames is None else str(caps.max_frames)
            lines.append(
                f"  {direction}: coords={caps.native_coordinate_system}, max_frames={frames}"
                + (f", requires {caps.required_fields}" if caps.required_fields else "")
            )
            for path in sorted(caps.fields):
                cell = caps.fields[path]
                note = f"  — {cell.notes}" if cell.notes else ""
                lines.append(f"      {path:<40} {_CAP.get(cell.level, str(cell.level))}{note}")
            for note in caps.lossy_notes:
                lines.append(f"      (lossy) {note}")
        lines.append("")
    return "\n".join(lines).rstrip()


#: Copy-paste values for the ``--recover`` flag, per (scenario, choice). Only choices that need a
#: parameter appear; everything else renders as ``scenario=choice``. Values are *examples the user
#: edits*, never defaults the engine applies (P4): the engine still requires the flag to be passed.
_RECOVER_EXAMPLES: dict[tuple[str, str], str] = {
    ("missing_lattice", "bounding_box"): "missing_lattice=bounding_box,padding_ang=5.0",
    ("frame_selection", "index"): "frame_selection=index,frame_index=0",
    ("asedb_row_selection", "index"): "asedb_row_selection=index,row=0",
    # The LAMMPS form (type:symbol pairs); the space is part of the value, so the flag is quoted.
    ("missing_species", "species_map"): "missing_species=species_map,species=1:Si 2:O",
    # The temperature is an example the user edits; the seed is explicit (no hidden default).
    (
        "missing_velocities",
        "maxwell_boltzmann",
    ): "missing_velocities=maxwell_boltzmann,temperature_K=300,seed=0",  # needs masses (see text)
}


def _recover_flag(scenario: str, choice: str) -> str | None:
    """The ready-to-copy ``--recover`` flag, or ``None`` for a choice that cannot be written as a
    bare flag (it needs data the user must supply, e.g. a 3x3 lattice or a species list)."""
    if (scenario, choice) in _RECOVER_EXAMPLES:
        spec = _RECOVER_EXAMPLES[(scenario, choice)]
        return f'--recover "{spec}"' if " " in spec else f"--recover {spec}"
    if choice == "upload_reference":
        # The CLI parses the second file itself (``file=PATH``); the user substitutes the path.
        return f"--recover {scenario}=upload_reference,file=REFERENCE_FILE"
    if (scenario, choice) in _NO_FLAG_HINTS:
        return None
    return f"--recover {scenario}={choice}"


#: Choices that cannot be written as a ``--recover`` flag, with the reason shown to the user.
_API_ONLY = "no --recover flag exists for this choice; use the Web UI or the HTTP API"
_NO_FLAG_HINTS: dict[tuple[str, str], str] = {
    ("missing_lattice", "manual_input"): _API_ONLY,
    ("missing_masses", "manual_input"): _API_ONLY,
    ("missing_lattice", "non_periodic"): "not yet available in this version; it is refused",
    # `all` is valid only through --batch (a single-file convert refuses it).
    ("asedb_row_selection", "all"): "only available through --batch, not a single-file convert",
}


def render_recovery_guidance(report: ConversionReport) -> str:
    """For a refused/``awaiting_recovery`` report: each unresolved scenario's plain-language
    description, its offered choices with descriptions, and a ready-to-copy ``--recover`` flag
    (Q1). Empty string when nothing is unresolved — the caller prints nothing."""
    refusal = report.refusal if isinstance(report.refusal, dict) else {}
    unresolved = refusal.get("unresolved_scenarios", []) if refusal else []
    if not unresolved:
        return ""
    lines = ["", "To resolve, re-run with one of these choices per scenario:"]
    for entry in unresolved:
        scenario = str(entry.get("scenario"))
        lines.append(f"  {scenario} — {describe_scenario(scenario)}")
        if entry.get("detail"):
            lines.append(f"    ({entry['detail']})")
        for choice in entry.get("options", []):
            lines.append(f"    {choice}: {describe_choice(scenario, str(choice))}")
            flag = _recover_flag(scenario, str(choice))
            lines.append(
                f"      {flag}"
                if flag
                else f"      ({_NO_FLAG_HINTS.get((scenario, str(choice)), _API_ONLY)})"
            )
    return "\n".join(lines)


def render_scenarios(names: list[str]) -> str:
    """Human view of the recovery catalog for ``xtalate scenarios [SCENARIO]``."""
    from xtalate.recovery.scenarios import SCENARIO_HAZARD

    lines: list[str] = []
    for name in names:
        lines.append(f"{name}  [{SCENARIO_HAZARD[name].value}]")
        lines.append(f"  {describe_scenario(name)}")
        for choice in _offered_choices(name):
            lines.append(f"    {choice}: {describe_choice(name, choice)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _offered_choices(scenario: str) -> list[str]:
    """Union of the choices ``available_options`` can offer for ``scenario`` over every target
    capability combination, in first-seen order (the catalog view is target-independent; a real
    refusal shows the pair-specific subset)."""
    import itertools

    from xtalate.recovery.scenarios import available_options

    seen: list[str] = []
    for a, b, c, d in itertools.product([False, True], repeat=4):
        for choice in available_options(
            scenario,
            target_can_be_nonperiodic=a,
            target_supports_multifile=b,
            target_field_optional=c,
            permissive_mode=d,
        ):
            if choice not in seen:
                seen.append(choice)
    return seen


def render_dry_run(dry: DryRun) -> str:
    """Human summary of ``convert --dry-run``: what a real run would do, lose and ask for. Reads
    the draft report; nothing here is a result and nothing was written."""
    report = dry.report
    lines = [
        f"Dry run: {report.source.get('format_id')} -> {report.target.get('format_id')} "
        "(nothing was written)."
    ]
    for applied in dry.applied:
        lines.append(f"  would apply repair {applied.operation}: {applied.description}")
        for hazard in applied.hazards:
            lines.append(f"    ! [{hazard.code}] {hazard.message}")
    if report.status == "completed":
        lines.append("  A real run would complete with no recovery choice.")
    else:
        lines.append("  A real run would pause for a recovery choice:")
        refusal = report.refusal if isinstance(report.refusal, dict) else {}
        if refusal.get("message"):
            lines.append(f"    {refusal['message']}")
    lines.append(render_conversion(report))
    guidance = render_recovery_guidance(report)
    if guidance:
        lines.append(guidance)
    return "\n".join(lines)
