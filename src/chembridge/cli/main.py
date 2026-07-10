"""The ``chembridge`` command-line interface (MASTER_SPEC Appendix A).

A thin presenter over the engines (Part 1 §2): it parses arguments, calls the library, and either
renders the report schemas of Parts 3–5 as a terminal inventory or emits them verbatim as JSON
(``--json``). It contains no scientific logic. Recovery is **preset-only** — the ``--recover`` flag
is the CLI form of ``recovery_choices`` — and a conversion needing a choice the caller did not
supply *refuses* (exit 2), never prompts: interactive recovery belongs to the job-driven UI, and a
second consent flow in a TTY would be a second thing to keep honest (Appendix A, rejected note).

Exit codes (§A.2) make the CLI CI-native without parsing stdout:
``0`` ok · ``2`` refused · ``3`` validation failed · ``4`` parse error ·
``5`` passed-with-warnings under ``--mode strict`` · ``1`` usage/internal error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from chembridge import __version__
from chembridge.capabilities import Registry
from chembridge.cli import render
from chembridge.conversion import (
    ConversionEngine,
    ConversionReport,
    build_expected_object,
    capability_path,
)
from chembridge.discovery import DiscoveryEngine
from chembridge.registry import default_registry
from chembridge.sdk import ParseError
from chembridge.validation import (
    ToleranceProfile,
    ValidationEngine,
    ValidationReport,
    rethreshold,
)

# Exit codes (Appendix A §A.2).
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_VALIDATION_FAILED = 3
EXIT_PARSE_ERROR = 4
EXIT_STRICT_WARNINGS = 5


class _Parser(argparse.ArgumentParser):
    """Argparse exits ``2`` on usage errors, but ``2`` is our *refused* code — remap to ``1``."""

    def error(self, message: str) -> Any:  # noqa: ANN401 - argparse signature.
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    registry = default_registry()
    try:
        handler = {
            "inspect": _cmd_inspect,
            "convert": _cmd_convert,
            "validate": _cmd_validate,
            "capabilities": _cmd_capabilities,
        }[args.command]
        return handler(args, registry)
    except ParseError as exc:
        for issue in exc.issues:
            print(f"parse error [{issue.code}]: {issue.message}", file=sys.stderr)
        return EXIT_PARSE_ERROR
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


class _UsageError(Exception):
    """A caller mistake surfaced after argparse (bad --recover spec, unknown profile, …) → exit 1."""


# --- commands ------------------------------------------------------------------------------------


def _cmd_inspect(args: argparse.Namespace, registry: Registry) -> int:
    data = _read_bytes(args.file)
    report = DiscoveryEngine(registry).discover(
        data, filename=Path(args.file).name, format_override=args.format
    )
    if args.report:
        _write_json(args.report, report.model_dump(mode="json"))
    if args.json:
        print(_json(report.model_dump(mode="json")))
    else:
        print(render.render_discovery(report))
    return EXIT_OK


def _cmd_convert(args: argparse.Namespace, registry: Registry) -> int:
    data = _read_bytes(args.file)
    source, source_format = _parse_source(registry, data, args.file, args.format)
    tolerance_name = _tolerance_name(args.tolerance_profile)
    result = ConversionEngine(registry).convert(
        source,
        source_format_id=source_format,
        target_format_id=args.to,
        source_filename=Path(args.file).name,
        target_filename=Path(args.output).name if args.output else None,
        mode=args.mode,
        recovery_choices=_parse_recover(args.recover),
        acknowledge_loss=args.acknowledge_loss,
        acknowledge_parse_warnings=args.acknowledge_parse_warnings,
        tolerance_profile=tolerance_name,
    )
    report = result.report

    if args.report:
        _write_json(args.report, report.model_dump(mode="json"))
    if args.validation_report and result.validation is not None:
        _write_json(args.validation_report, result.validation.model_dump(mode="json"))

    if args.json:
        print(
            _json(
                {
                    "conversion_report": report.model_dump(mode="json"),
                    "validation_report": (
                        result.validation.model_dump(mode="json") if result.validation else None
                    ),
                }
            )
        )
    else:
        print(render.render_conversion(report))
        if result.validation is not None:
            print()
            print(render.render_validation(result.validation))
        _emit_output(args, result.output)

    return _convert_exit_code(report, result.validation, args.mode)


def _cmd_validate(args: argparse.Namespace, registry: Registry) -> int:
    if args.source or args.output:
        report = _validate_full_reparse(args, registry)
    else:
        report = _validate_rethreshold(args)

    if args.validation_report and (args.source or args.output):
        _write_json(args.validation_report, report.model_dump(mode="json"))
    if args.json:
        print(_json(report.model_dump(mode="json")))
    else:
        print(render.render_validation(report))

    return EXIT_VALIDATION_FAILED if report.status == "failed" else EXIT_OK


def _cmd_capabilities(args: argparse.Namespace, registry: Registry) -> int:
    matrix = registry.capability_matrix()
    format_ids = {p.format_id for p in registry.parsers()} | {
        e.format_id for e in registry.exporters()
    }
    if args.format_id:
        if args.format_id not in format_ids:
            raise _UsageError(f"unknown format {args.format_id!r}; known: {sorted(format_ids)}")
        format_ids = {args.format_id}

    declarations: dict[str, dict[str, Any]] = {}
    for fid in format_ids:
        directions: dict[str, Any] = {}
        for direction in ("read", "write"):
            try:
                directions[direction] = matrix.get(fid, direction)
            except KeyError:
                continue
        declarations[fid] = directions

    if args.json:
        payload = {
            fid: {d: caps.model_dump(mode="json") for d, caps in dirs.items()}
            for fid, dirs in declarations.items()
        }
        print(_json(payload))
    else:
        print(render.render_capabilities(declarations))
    return EXIT_OK


# --- validate helpers ----------------------------------------------------------------------------


def _validate_full_reparse(args: argparse.Namespace, registry: Registry) -> ValidationReport:
    """Offline full re-parse re-validation (Part 5 §4.5): reconstruct the expected object from the
    source file + the Conversion Report's write plan, re-parse the output, and diff."""
    if not (args.source and args.output and args.conversion_report):
        raise _UsageError(
            "full re-parse re-validation needs --output, --source, and --conversion-report"
        )
    conversion = ConversionReport.model_validate_json(Path(args.conversion_report).read_text())
    if conversion.supplied:
        # The fabricated values (e.g. a recovery lattice) are not in the source and not stored in
        # the report, so the expected object cannot be faithfully rebuilt offline. Refuse rather
        # than validate against a wrong reference (that would be silently wrong — worse than
        # refusing). Re-thresholding the original ValidationReport still works (Part 5 §4.5).
        raise _UsageError(
            "offline full re-parse re-validation is unavailable for conversions with "
            "recovery-supplied fields in v0.1 (the fabricated values cannot be reconstructed from "
            "the source); re-threshold the original ValidationReport instead (omit --source)"
        )
    target_format = conversion.target.get("format_id")
    if not isinstance(target_format, str):
        raise _UsageError("conversion report has no target.format_id")

    source_bytes = _read_bytes(args.source)
    source, _ = _parse_source(registry, source_bytes, args.source, None)
    plan = {capability_path(e.path) for e in conversion.preserved}
    expected = build_expected_object(source, plan, target_format)
    output_bytes = _read_bytes(args.output)
    return ValidationEngine(registry).validate(
        expected=expected,
        output=output_bytes,
        target_format_id=target_format,
        conversion_report=conversion,
        tolerance=ToleranceProfile.named(_tolerance_name(args.tolerance_profile)),
    )


def _validate_rethreshold(args: argparse.Namespace) -> ValidationReport:
    """Re-threshold a stored Validation Report under a new profile (Part 5 §4.5) — no re-parse."""
    if not args.validation_report:
        raise _UsageError(
            "re-thresholding needs --validation-report REPORT.json (and no --source/--output)"
        )
    stored = ValidationReport.model_validate_json(Path(args.validation_report).read_text())
    return rethreshold(stored, ToleranceProfile.named(_tolerance_name(args.tolerance_profile)))


# --- shared helpers ------------------------------------------------------------------------------


def _parse_source(
    registry: Registry, data: bytes, path: str, format_override: str | None
) -> tuple[Any, str]:
    """Sniff + parse a source file, returning (canonical, format_id). Reuses the Discovery Engine's
    sniff-then-parse so the CLI and inspect agree on what a file is (no second detection path)."""
    from chembridge.discovery import Sniffer

    fmt = format_override or Sniffer(registry).sniff(data, Path(path).name).format_id
    if fmt is None:
        raise ParseError(
            [
                _unknown_format_issue(
                    "could not determine the source format; pass --format to override"
                )
            ]
        )
    if fmt not in {p.format_id for p in registry.parsers()}:
        raise ParseError([_unknown_format_issue(f"no parser registered for format {fmt!r}")])
    import io

    canonical = registry.get_parser(fmt).parse(io.BytesIO(data), filename=Path(path).name).canonical
    return canonical, fmt


def _unknown_format_issue(message: str) -> Any:
    from chembridge.sdk import ParseIssue

    return ParseIssue(severity="error", code="UNKNOWN_FORMAT", message=message)


def _parse_recover(specs: list[str] | None) -> dict[str, dict[str, Any]]:
    """Parse repeated ``--recover SCENARIO=CHOICE[,param=value…]`` into ``recovery_choices``."""
    choices: dict[str, dict[str, Any]] = {}
    for spec in specs or []:
        if "=" not in spec:
            raise _UsageError(f"--recover {spec!r} must be SCENARIO=CHOICE[,param=value…]")
        scenario, rest = spec.split("=", 1)
        parts = rest.split(",")
        choice = parts[0]
        params: dict[str, Any] = {}
        for param in parts[1:]:
            if "=" not in param:
                raise _UsageError(f"--recover parameter {param!r} must be name=value")
            name, value = param.split("=", 1)
            params[name] = _coerce(value)
        choices[scenario] = {"choice": choice, "parameters": params}
    return choices


def _coerce(value: str) -> Any:
    """Coerce a CLI parameter string to int, then float, else leave it a string."""
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def _tolerance_name(value: str | None) -> str:
    """v0.1 supports only named profiles (default/strict/loose); a FILE table is a v0.2 seam."""
    name = value or "default"
    try:
        ToleranceProfile.named(name)
    except ValueError as exc:
        raise _UsageError(str(exc)) from exc
    return name


def _convert_exit_code(
    report: ConversionReport, validation: ValidationReport | None, mode: str
) -> int:
    if report.status == "refused":
        return EXIT_REFUSED
    if validation is None:
        return EXIT_OK
    if validation.status == "failed":
        return EXIT_VALIDATION_FAILED
    if validation.status == "passed_with_warnings" and mode == "strict":
        return EXIT_STRICT_WARNINGS
    return EXIT_OK


def _emit_output(args: argparse.Namespace, output: bytes | None) -> None:
    if output is None:
        return
    if args.output:
        Path(args.output).write_bytes(output)
        print(f"\nWrote {args.to} output to {args.output}")
    else:
        print(f"\n----- {args.to} output -----")
        sys.stdout.write(output.decode())


def _read_bytes(path: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}") from exc


def _write_json(path: str, payload: Any) -> None:
    Path(path).write_text(_json(payload) + "\n")


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


# --- argument parser -----------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="chembridge", description="Audit-first computational-chemistry file conversion."
    )
    parser.add_argument("--version", action="version", version=f"chembridge {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_inspect = sub.add_parser(
        "inspect", help="Run the Information Discovery Engine (✓/✗ inventory)."
    )
    p_inspect.add_argument("file")
    p_inspect.add_argument("--format", metavar="FORMAT_ID", help="Override format sniffing.")
    p_inspect.add_argument("--report", metavar="PATH", help="Write the DiscoveryReport JSON here.")
    p_inspect.add_argument("--json", action="store_true", help="Print the DiscoveryReport JSON.")

    p_convert = sub.add_parser(
        "convert", help="Full pipeline: parse → pre-flight → recovery → export → validate."
    )
    p_convert.add_argument("file")
    p_convert.add_argument("--to", required=True, metavar="FORMAT_ID", help="Target format.")
    p_convert.add_argument("-o", "--output", metavar="PATH", help="Write the converted file here.")
    p_convert.add_argument("--format", metavar="FORMAT_ID", help="Override source format sniffing.")
    p_convert.add_argument("--mode", choices=("permissive", "strict"), default="permissive")
    p_convert.add_argument(
        "--recover",
        action="append",
        metavar="SCENARIO=CHOICE[,param=value…]",
        help="Preset recovery choice (repeatable).",
    )
    p_convert.add_argument("--acknowledge-loss", action="store_true")
    p_convert.add_argument("--acknowledge-parse-warnings", action="store_true")
    p_convert.add_argument("--tolerance-profile", metavar="NAME", help="default|strict|loose.")
    p_convert.add_argument("--report", metavar="PATH", help="Write the ConversionReport JSON here.")
    p_convert.add_argument(
        "--validation-report", metavar="PATH", help="Write the ValidationReport JSON here."
    )
    p_convert.add_argument(
        "--json", action="store_true", help="Print both reports as one JSON object."
    )

    p_validate = sub.add_parser(
        "validate", help="Offline re-parse re-validation, or re-threshold a stored report."
    )
    p_validate.add_argument(
        "--output", metavar="FILE", help="Converted output file (full re-parse mode)."
    )
    p_validate.add_argument(
        "--source", metavar="FILE", help="Original source file (full re-parse mode)."
    )
    p_validate.add_argument(
        "--conversion-report", metavar="PATH", help="ConversionReport JSON (full re-parse mode)."
    )
    p_validate.add_argument(
        "--validation-report",
        metavar="PATH",
        help="Write the ValidationReport here (full re-parse), or — alone — read it to re-threshold.",
    )
    p_validate.add_argument("--tolerance-profile", metavar="NAME", help="default|strict|loose.")
    p_validate.add_argument("--json", action="store_true", help="Print the ValidationReport JSON.")

    p_caps = sub.add_parser("capabilities", help="Print the Capability Matrix.")
    p_caps.add_argument("format_id", nargs="?", metavar="FORMAT_ID", help="Limit to one format.")
    p_caps.add_argument("--json", action="store_true", help="Print the matrix JSON.")

    return parser


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - module-run convenience.
    raise SystemExit(main())
