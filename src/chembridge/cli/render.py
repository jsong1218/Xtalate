"""Human-readable terminal renderers for the report schemas (MASTER_SPEC Appendix A, Part 3 §6.3).

Pure functions: report model in, plain-text string out. The CLI is a *thin presenter* (Part 1 §2)
— these renderers add no scientific logic and invent no information the reports do not already
carry; `--json` bypasses them entirely and emits the pydantic models verbatim. ASCII glyphs keep
the output legible in any terminal/pipe (✓/✗ are the one concession, matching the §6.3 inventory).
"""

from __future__ import annotations

from chembridge.conversion.report import ConversionReport
from chembridge.discovery.report import DiscoveryReport
from chembridge.sdk import CapabilityLevel, FormatCapabilities
from chembridge.validation.report import ValidationReport

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


def render_capabilities(declarations: dict[str, dict[str, FormatCapabilities]]) -> str:
    lines: list[str] = []
    for format_id in sorted(declarations):
        directions = declarations[format_id]
        any_caps = next(iter(directions.values()))
        lines.append(f"{any_caps.format_name} [{format_id}]")
        for direction in ("read", "write"):
            caps = directions.get(direction)
            if caps is None:
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
