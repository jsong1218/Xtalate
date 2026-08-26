"""The ``xtalate`` command-line interface (MASTER_SPEC Appendix A).

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
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from xtalate import __version__
from xtalate.capabilities import Registry
from xtalate.capabilities.registry import InvalidCapabilityDeclaration
from xtalate.cli import render
from xtalate.conversion import (
    BatchManifestError,
    ConversionEngine,
    ConversionReport,
    SourceEntry,
    build_expected_object,
    load_manifest,
    parse_recovery_presets,
    parse_with_recovery,
    run_batch,
)
from xtalate.conversion.batch import RecoveryPresetError
from xtalate.discovery import DiscoveryEngine
from xtalate.recovery import RecoveryError
from xtalate.registry import PluginLoadError, default_registry
from xtalate.sdk import ParseError
from xtalate.validation import (
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
    # Registry construction gets its own guard: a broken *installed plugin* (an import failure,
    # a malformed declaration, a format_id collision) must surface as a clean, attributed error
    # and exit code — not a raw traceback. Every command still refuses to run until the offending
    # distribution is fixed or uninstalled: discovery never silently skips a broken plugin
    # (Part 3 §7.1), so this changes the failure's *surface*, not the fail-loud policy.
    try:
        registry = default_registry()
    except (PluginLoadError, InvalidCapabilityDeclaration) as exc:
        print(f"error: broken installed plugin: {exc}", file=sys.stderr)
        print(
            "  fix or uninstall the offending distribution; plugins are discovered for every "
            "command and a broken one is never silently skipped",
            file=sys.stderr,
        )
        return EXIT_USAGE
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
            if issue.recovery_hint:
                # A recoverable error: point the user at the preset that would resolve it, so a
                # refused parse is actionable rather than a dead end (Part 4 §3.3).
                print(
                    f"  recoverable (hint: {issue.recovery_hint}) — re-run with a matching "
                    "--recover preset (e.g. --recover missing_species=species_map,species=... or "
                    "--recover truncate_corrupt_tail=truncate)",
                    file=sys.stderr,
                )
        return EXIT_PARSE_ERROR
    except RecoveryError as exc:
        # An invalid --recover preset (a bad choice or missing parameter) is a caller error, not
        # a refusal: surface it as a clean usage message, never a traceback (per the engine docs).
        print(f"error: invalid --recover preset: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except RecoveryPresetError as exc:
        # A malformed preset string (from the CLI or a batch manifest) is the same caller mistake.
        print(f"error: invalid recovery preset: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BatchManifestError as exc:
        # A malformed or self-inconsistent batch manifest is a caller mistake, like a bad
        # --recover preset: clean usage error (exit 1), never a traceback.
        print(f"error: invalid batch manifest: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except _UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


class _UsageError(Exception):
    """A caller mistake surfaced after argparse (bad --recover, unknown profile) → exit 1."""


# --- commands ------------------------------------------------------------------------------------


def _cmd_inspect(args: argparse.Namespace, registry: Registry) -> int:
    if Path(args.file).is_dir():
        files = _read_directory(args.file)
        report = DiscoveryEngine(registry).discover_dir(
            files, dirname=Path(args.file).name, format_override=args.format
        )
        if args.report:
            _write_json(args.report, report.model_dump(mode="json"))
        if args.json:
            print(_json(report.model_dump(mode="json")))
        else:
            print(render.render_discovery(report))
        return EXIT_OK
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
    if args.batch:
        if args.file is not None:
            raise _UsageError("convert takes FILE *or* --batch MANIFEST, not both")
        return _cmd_convert_batch(args, registry)
    if args.file is None:
        raise _UsageError("convert needs FILE (or --batch MANIFEST)")
    if args.to is None:
        raise _UsageError("convert needs --to FORMAT_ID (in batch mode the manifest carries it)")
    is_directory = Path(args.file).is_dir()
    result = None if is_directory else _convert_streamed(args, registry)
    streamed = result is not None
    if result is None:
        directory_files = _read_directory(args.file) if is_directory else None
        data = None if is_directory else _read_bytes(args.file)
        tolerance = _resolve_tolerance(args.tolerance_profile)
        recovery_choices = _parse_recover(args.recover)
        _inject_references(registry, recovery_choices)
        # parse-time recovery (missing_species / truncate_corrupt_tail) is applied here, before the
        # engine, if a matching preset was supplied; otherwise the recoverable parse error stands.
        parsed = parse_with_recovery(
            registry,
            data,
            filename=Path(args.file).name,
            format_override=args.format,
            recovery_choices=recovery_choices,
            directory_files=directory_files,
            dirname=Path(args.file).name if is_directory else None,
        )
        result = ConversionEngine(registry).convert(
            parsed.canonical,
            source_format_id=parsed.format_id,
            target_format_id=args.to,
            source_filename=Path(args.file).name,
            target_filename=Path(args.output).name if args.output else None,
            mode=args.mode,
            recovery_choices=recovery_choices,
            parse_recovery=parsed,
            acknowledge_loss=args.acknowledge_loss,
            acknowledge_parse_warnings=args.acknowledge_parse_warnings,
            tolerance_profile=tolerance,
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

    # The output file is written regardless of --json — the reports and the artifact are
    # independent outputs. In --json mode only the stdout dump is suppressed (it would corrupt the
    # JSON stream); the file-write notice always goes to stderr so stdout stays pure.
    if streamed:
        # The streaming engine already wrote the artifact frame by frame; only the notice remains.
        print(f"Wrote {args.to} output to {args.output}", file=sys.stderr)
    else:
        _emit_output(args, result, human=not args.json)

    _ring_completion_bell(args)
    return _convert_exit_code(report, result.validation, args.mode)


def _cmd_convert_batch(args: argparse.Namespace, registry: Registry) -> int:
    """The thin ``convert --batch`` presenter (M54-S3): read the manifest, run the proven
    :func:`run_batch`, then emit — the ``BatchReport`` verbatim under ``--json``, a human view
    otherwise. The batch exit code is the **worst per-file outcome** under the existing 0–5
    vocabulary (reusing :func:`_convert_exit_code` per entry); a malformed manifest, a
    manifest-level refusal (unknown target, empty sources, a non-assemble-capable assemble), or a
    conflicting per-file flag is a usage error (exit 1).

    The CLI adds **no batch logic**: every manifest decision, failure-isolation rule, and
    output-mode behaviour lives in the library, exactly the ``run_batch`` a pipeline or M58's
    API job would call. In batch mode the shared conversion settings (``--mode``/``--recover``/
    ``--tolerance-profile``/the acknowledge flags) come from the manifest, so passing them on
    the command line is refused rather than silently ignored."""
    for flag in _BATCH_CONFLICTS(args):
        raise _UsageError(
            f"{flag} cannot be used with --batch: the manifest carries the shared conversion "
            "settings; set them there (the manifest wins by design)"
        )
    if args.output is None:
        raise _UsageError(
            "batch conversion needs -o: a directory (per-file mode) or a file path (assemble mode)"
        )
    manifest = load_manifest(args.batch)
    report = run_batch(
        manifest,
        registry,
        output=args.output,
        fail_fast=args.fail_fast,
    )
    if args.json:
        print(_json(report.model_dump(mode="json")))
    else:
        print(render.render_batch(report))
    # Status line to stderr so a --json run keeps stdout as clean JSON (the single-file
    # convention): the artifacts were written by run_batch; the CLI only reports where.
    if manifest.output_mode == "assemble":
        print(
            f"Wrote assembled {manifest.target} output to {args.output}",
            file=sys.stderr,
        )
    else:
        print(
            f"Wrote {report.tallies.converted} {manifest.target} file(s) to {args.output}/",
            file=sys.stderr,
        )
    _ring_completion_bell(args)
    return _batch_exit_code(report)


def _BATCH_CONFLICTS(args: argparse.Namespace) -> list[str]:
    """The per-file flags that are meaningless (and would be silently ignored) in batch mode,
    where the manifest carries the shared settings. Each is a real value the user set — a
    no-op default (``--mode permissive``) is not a conflict."""
    conflicts = []
    if args.mode == "strict":
        conflicts.append("--mode")
    if args.recover:
        conflicts.append("--recover")
    if args.tolerance_profile is not None:
        conflicts.append("--tolerance-profile")
    if args.acknowledge_loss:
        conflicts.append("--acknowledge-loss")
    if args.acknowledge_parse_warnings:
        conflicts.append("--acknowledge-parse-warnings")
    if args.format is not None:
        conflicts.append("--format")
    if args.report is not None:
        conflicts.append("--report")
    if args.validation_report is not None:
        conflicts.append("--validation-report")
    return conflicts


def _batch_exit_code(report: Any) -> int:
    """The batch exit code = the **worst per-file outcome** under the existing 0–5 vocabulary:
    each entry folds through the same single-file logic (:func:`_convert_exit_code`) with its
    *effective* mode (a per-file override may be stricter than the manifest), and the maximum
    wins. ``EXIT_USAGE`` (1) is never produced here — a manifest-level caller mistake exits
    before any conversion runs."""
    worst = EXIT_OK
    # Recover each entry's effective mode by *path*, not by position: a multi-structure container
    # (a multi-row `.db`) fans out to N per-row entries (M55-S3), so `entries` is no longer a
    # length-1:1 positional prefix of `manifest.sources`. Each fanned entry's `source` is
    # `<container path>::row=<i>`, so strip the row suffix to find its container's override. A
    # missing map entry falls back to the shared manifest mode (never a KeyError).
    override_by_path = {
        source.path: source.override
        for source in report.manifest.sources
        if isinstance(source, SourceEntry)
    }
    for entry in report.entries:
        if entry.status == "failed":
            code = EXIT_PARSE_ERROR
        elif entry.status == "refused":
            code = EXIT_REFUSED
        elif entry.conversion is not None:
            mode = report.manifest.mode
            container = entry.source.split("::row=", 1)[0]  # mirrors batch._ROW_LABEL_SEP
            override = override_by_path.get(container)
            if override is not None and override.mode:
                mode = override.mode
            code = _convert_exit_code(entry.conversion, entry.validation, mode)
        else:
            code = EXIT_OK
        worst = max(worst, code)
    return worst


def _convert_streamed(args: argparse.Namespace, registry: Registry) -> Any | None:
    """Route an eligible ``convert`` through the streaming engines, holding one frame resident
    (M12/M13; the post-v0.3-review wiring, DECISIONS.md D63) — before it, the CLI always
    materialized and the library-only streaming spine never reached `xtalate convert`. Returns
    ``None`` whenever the invocation is not a streaming case; the caller then runs the
    materialized path unchanged. Which path ran is not observable in the artifact or the reports:
    the engines guarantee byte-identical output and an identical Conversion Report (M12 standing
    rule 3), pinned here by the CLI equality tests.

    The gates, all static: an ``-o`` file target (the no-``-o`` stdout dump needs the bytes in
    memory anyway); permissive mode (the strict acknowledgment protocol —
    ``UNACKNOWLEDGED_PARSE_WARNINGS`` — is implemented by the materialized engine only); recovery
    presets empty (``convert_stream``) or exactly a ``first``/``last``/``index``
    ``frame_selection`` (``convert_stream_select``); and the engines' own capability gates.
    ``convert_stream_select``'s runtime exclusions (constraints present, a fabricative recovery
    still needed) raise ``ValueError`` and the source is re-read from disk on the materialized
    path — a second pass, never a wrong report. The artifact is streamed into a temp file in the
    output directory and renamed over ``-o`` only on success, so a mid-stream parse error leaves
    a pre-existing file at ``-o`` untouched — exactly like the materialized path, which writes
    the output only after the whole conversion succeeded.
    """
    if not args.output or args.mode == "strict":
        return None
    recovery_choices = _parse_recover(args.recover)
    frame_selection: dict[str, Any] | None = None
    if recovery_choices:
        if set(recovery_choices) != {"frame_selection"}:
            return None
        frame_selection = recovery_choices["frame_selection"]
        if frame_selection.get("choice") not in ("first", "last", "index"):
            return None

    from xtalate.discovery import Sniffer
    from xtalate.discovery.sniffer import HEAD_SIZE

    source_path = Path(args.file)
    fmt = args.format
    if fmt is None:
        try:
            with source_path.open("rb") as stream:
                head = stream.read(HEAD_SIZE)
        except OSError:
            return None  # the materialized path raises the canonical file error
        fmt = Sniffer(registry).sniff(head, source_path.name).format_id
    if fmt is None or fmt not in {p.format_id for p in registry.parsers()}:
        return None  # the materialized path raises the canonical UNKNOWN_FORMAT error
    engine = ConversionEngine(registry)
    try:
        if frame_selection is None:
            if not engine.streaming_eligible(fmt, args.to):
                return None
        elif not engine.frame_selection_streaming_eligible(fmt, args.to):
            return None
    except KeyError:
        return None  # unknown --to: the materialized path surfaces it as it always has

    out_path = Path(args.output)
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(out_path.parent), prefix=f".{out_path.name}.", suffix=".partial"
        )
    except OSError:
        return None  # unwritable target directory: fail exactly as the materialized write would
    tmp_path: str | None = tmp_name
    try:
        with source_path.open("rb") as source, os.fdopen(fd, "w+b") as output:
            try:
                if frame_selection is None:
                    result = engine.convert_stream(
                        source,
                        source_format_id=fmt,
                        target_format_id=args.to,
                        output=output,
                        source_filename=source_path.name,
                        target_filename=out_path.name,
                        mode=args.mode,
                        tolerance_profile=_resolve_tolerance(args.tolerance_profile),
                        acknowledge_loss=args.acknowledge_loss,
                    )
                else:
                    result = engine.convert_stream_select(
                        source,
                        source_format_id=fmt,
                        target_format_id=args.to,
                        output=output,
                        frame_selection=frame_selection,
                        source_filename=source_path.name,
                        target_filename=out_path.name,
                        mode=args.mode,
                        tolerance_profile=_resolve_tolerance(args.tolerance_profile),
                        acknowledge_loss=args.acknowledge_loss,
                    )
            except RecoveryError:
                raise  # a caller error (bad frame_selection preset), identical either path
            except ValueError:
                return None  # engine runtime exclusion ("use convert()"): materialize instead
        os.replace(tmp_name, out_path)
        tmp_path = None
        return result
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


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
    # The source/target split is deliberate (D159): the union admits a parser-only format
    # as a *source* (its read row renders; see render_capabilities) while it stays absent
    # from every exporter-derived target enumeration — a parser-only format is never a
    # conversion target, so it never appears as a `--to` option or a write row here.
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
    # Reconstruct the write_plan from the report's preserved paths at their declared granularity:
    # container-level for ordinary fields, per-key for a custom container a target writes only
    # specific keys of (`build_expected_object` → `_apply_write_plan` accepts either). Collapsing a
    # per-key path to its container here would wrongly re-admit dropped foreign keys into the
    # reference object.
    plan = {e.path for e in conversion.preserved}
    expected = build_expected_object(source, plan, target_format)
    output_bytes = _read_bytes(args.output)
    return ValidationEngine(registry).validate(
        expected=expected,
        output=output_bytes,
        target_format_id=target_format,
        conversion_report=conversion,
        tolerance=_resolve_tolerance(args.tolerance_profile),
    )


def _validate_rethreshold(args: argparse.Namespace) -> ValidationReport:
    """Re-threshold a stored Validation Report under a new profile (Part 5 §4.5) — no re-parse."""
    if not args.validation_report:
        raise _UsageError(
            "re-thresholding needs --validation-report REPORT.json (and no --source/--output)"
        )
    stored = ValidationReport.model_validate_json(Path(args.validation_report).read_text())
    return rethreshold(stored, _resolve_tolerance(args.tolerance_profile))


# --- shared helpers ------------------------------------------------------------------------------


def _parse_source(
    registry: Registry, data: bytes, path: str, format_override: str | None
) -> tuple[Any, str]:
    """Sniff + parse a source file, returning (canonical, format_id). Reuses the Discovery Engine's
    sniff-then-parse so the CLI and inspect agree on what a file is (no second detection path)."""
    from xtalate.discovery import Sniffer

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
    from xtalate.sdk import ParseIssue

    return ParseIssue(severity="error", code="UNKNOWN_FORMAT", message=message)


def _parse_recover(specs: list[str] | None) -> dict[str, dict[str, Any]]:
    """Parse repeated ``--recover SCENARIO=CHOICE[,param=value…]`` into ``recovery_choices``.

    The one preset grammar lives in the batch module (``conversion.batch.parse_recovery_presets``
    — shared with the batch manifest, so the CLI and the batch can never drift); the CLI only
    maps its error onto the usage-error surface."""
    try:
        return parse_recovery_presets(specs)
    except RecoveryPresetError as exc:
        raise _UsageError(f"--recover {exc}") from exc


def _inject_references(registry: Registry, recovery_choices: dict[str, dict[str, Any]]) -> None:
    """Resolve any ``file=PATH`` recovery parameter (``upload_reference``) into a parsed reference
    ``CanonicalObject`` under ``parameters['reference']`` (Part 4 §3.3). The CLI does the
    second-file parse so the Recovery Engine / parser hook receives a canonical object, not a path —
    keeping the library layer file-system-free."""
    for spec in recovery_choices.values():
        params = spec.get("parameters", {})
        ref_path = params.get("file")
        if ref_path is None:
            continue
        ref_bytes = _read_bytes(str(ref_path))
        params["reference"] = parse_with_recovery(
            registry, ref_bytes, filename=Path(str(ref_path)).name
        ).canonical


_NAMED_PROFILES = ("default", "strict", "loose")


def _resolve_tolerance(value: str | None) -> ToleranceProfile:
    """Resolve ``--tolerance-profile`` to a :class:`ToleranceProfile` (Part 5 §4.4).

    ``None`` or a named profile (``default``/``strict``/``loose``) resolves by name; anything else
    is treated as a path to a custom tolerance-table file. A ``.json`` file is parsed with
    ``json.load``; any other extension with ``yaml.safe_load``. Dispatching on the extension —
    rather than routing JSON through YAML — matters because PyYAML implements YAML 1.1, whose float
    grammar rejects dotless scientific notation (``1e-8`` parses as the *string* ``"1e-8"``, not a
    float), so a valid JSON table like ``{"forces": {"warn": 1e-8}}`` would otherwise fail with a
    confusing "must be a number" error. A bad name, a missing file, or a malformed/invalid table
    surfaces as a clean usage error (exit 1), never a traceback."""
    if value is None or value in _NAMED_PROFILES:
        return ToleranceProfile.named(value or "default")

    path = Path(value)
    if not path.is_file():
        raise _UsageError(
            f"--tolerance-profile {value!r} is neither a named profile "
            f"({', '.join(_NAMED_PROFILES)}) nor a readable file"
        )
    try:
        text = path.read_text()
        if path.suffix.lower() == ".json":
            mapping = json.loads(text)
        else:
            mapping = yaml.safe_load(text)
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        raise _UsageError(f"cannot read tolerance-table file {value!r}: {exc}") from exc
    try:
        return ToleranceProfile.from_mapping(path.stem, mapping)
    except ValueError as exc:
        raise _UsageError(f"invalid tolerance-table file {value!r}: {exc}") from exc


def _ring_completion_bell(args: argparse.Namespace) -> None:
    """The completion signal (v1.1 M39-S4, C2): a terminal bell when ``xtalate convert`` finishes.

    Rings **only** when stderr is a TTY — a piped or redirected stream never receives a control
    byte, so scripts and captured output stay clean — and only when the user has not opted out
    with ``--no-bell`` or the global ``XTALATE_NO_BELL`` env var (any non-empty value). It fires on
    either terminal outcome — a converted file **or** a refusal — because "finished" is the
    signal; the report itself says which. ``inspect``/``validate`` are deliberately out of scope:
    the maintainer asked for conversion finish.
    """
    if args.no_bell:
        return
    if os.environ.get("XTALATE_NO_BELL"):
        return
    if not sys.stderr.isatty():
        return
    sys.stderr.write("\a")
    sys.stderr.flush()


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


def _emit_output(args: argparse.Namespace, result: Any, *, human: bool) -> None:
    # `split_all` produced one file per frame (Part 4 §3.3): write the set into a directory.
    if result.outputs is not None:
        _emit_split_outputs(args, result.outputs, human=human)
        return
    if result.output_dir is not None:
        if not args.output:
            raise _UsageError(f"{args.to} writes a directory; pass -o DIR")
        directory = Path(args.output)
        directory.mkdir(parents=True, exist_ok=True)
        for relative, content in result.output_dir.items():
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        print(f"Wrote {args.to} output to {directory}/", file=sys.stderr)
        return
    output = result.output
    if output is None:
        return
    if args.output:
        Path(args.output).write_bytes(output)
        # Status line to stderr so a --json run keeps stdout as clean JSON.
        print(f"Wrote {args.to} output to {args.output}", file=sys.stderr)
    elif human:
        # No -o and human mode: dump the converted bytes to stdout for a quick look. In --json mode
        # with no -o there is nowhere clean to put the artifact, so it is simply not emitted.
        print(f"\n----- {args.to} output -----")
        sys.stdout.write(output.decode())


def _emit_split_outputs(args: argparse.Namespace, outputs: list[bytes], *, human: bool) -> None:
    """Write a ``split_all`` result — one file per frame — into the directory named by ``-o``."""
    if not args.output:
        raise _UsageError(
            "split_all produced one file per frame; pass -o DIR to name an output directory"
        )
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    # POSCAR/CONTCAR have no conventional extension; other formats take one from the format id.
    suffix = "" if args.to in ("poscar", "contcar") else f".{args.to}"
    stem = "POSCAR" if args.to in ("poscar", "contcar") else "frame"
    for i, chunk in enumerate(outputs):
        (directory / f"{stem}_{i:04d}{suffix}").write_bytes(chunk)
    # Status line to stderr so a --json run keeps stdout clean.
    print(f"Wrote {len(outputs)} {args.to} file(s) to {directory}/", file=sys.stderr)


def _read_directory(path: str) -> dict[str, bytes]:
    root = Path(path)
    if not root.is_dir():
        raise _UsageError(f"{path} is not a directory")
    known = {"type.raw", "type_map.raw"}
    files: dict[str, bytes] = {}
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        relative = child.relative_to(root).as_posix()
        if relative in known or (relative.startswith("set.") and relative.count("/") == 1):
            files[relative] = _read_bytes(str(child))
    return files


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
        prog="xtalate", description="Audit-first computational-chemistry file conversion."
    )
    parser.add_argument("--version", action="version", version=f"xtalate {__version__}")
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
    p_convert.add_argument(
        "file", nargs="?", help="Source file (omit when --batch MANIFEST is given)."
    )
    p_convert.add_argument(
        "--batch",
        metavar="MANIFEST",
        help="Convert every source in a YAML batch manifest (per-file or assemble mode); "
        "the manifest carries the target and the shared settings.",
    )
    p_convert.add_argument(
        "--fail-fast",
        action="store_true",
        help="Batch mode: stop at the first file that is not converted (default: partial "
        "completion with per-file honesty).",
    )
    p_convert.add_argument(
        "--to",
        metavar="FORMAT_ID",
        help="Target format (in batch mode the manifest carries it).",
    )
    p_convert.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Write the converted file here (batch: a directory for per-file mode, a file "
        "for assemble mode).",
    )
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
    p_convert.add_argument(
        "--tolerance-profile",
        metavar="NAME|FILE",
        help="default|strict|loose, or a custom tolerance-table file (YAML/JSON).",
    )
    p_convert.add_argument("--report", metavar="PATH", help="Write the ConversionReport JSON here.")
    p_convert.add_argument(
        "--validation-report", metavar="PATH", help="Write the ValidationReport JSON here."
    )
    p_convert.add_argument(
        "--json", action="store_true", help="Print both reports as one JSON object."
    )
    p_convert.add_argument(
        "--no-bell",
        action="store_true",
        help="Do not ring the terminal bell on completion (XTALATE_NO_BELL disables it globally).",
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
        help="Write the report (full re-parse), or — alone — read it to re-threshold.",
    )
    p_validate.add_argument(
        "--tolerance-profile",
        metavar="NAME|FILE",
        help="default|strict|loose, or a custom tolerance-table file (YAML/JSON).",
    )
    p_validate.add_argument("--json", action="store_true", help="Print the ValidationReport JSON.")

    p_caps = sub.add_parser("capabilities", help="Print the Capability Matrix.")
    p_caps.add_argument("format_id", nargs="?", metavar="FORMAT_ID", help="Limit to one format.")
    p_caps.add_argument("--json", action="store_true", help="Print the matrix JSON.")

    return parser


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - module-run convenience.
    raise SystemExit(main())
