"""The ``xtalate`` command-line interface (MASTER_SPEC Appendix A).

A thin presenter over the engines (Part 1 §2): it parses arguments, calls the library, and either
renders the report schemas of Parts 3–5 as a terminal inventory or emits them verbatim as JSON
(``--json``). It contains no scientific logic. Recovery is **preset-only** — the ``--recover`` flag
is the CLI form of ``recovery_choices`` — and a conversion needing a choice the caller did not
supply *refuses* (exit 2), never prompts: interactive recovery belongs to the job-driven UI, and a
second consent flow in a TTY would be a second thing to keep honest (Appendix A, rejected note).
Repair is user-initiated and **order-dependent** — the repeatable ``--repair``
``OPERATION[,param=value…]`` flag builds the ordered ``list[RepairRequest]`` (v1.7 M66; D255)
applied by the engine between parse and pre-flight; a bad request exits 1, and a blocked repair
(a cell-less wrap) refuses through the ordinary refusal path (exit 2) like any recovery the CLI
cannot resolve.

Exit codes (§A.2) make the CLI CI-native without parsing stdout:
``0`` ok · ``2`` refused · ``3`` validation failed · ``4`` parse error ·
``5`` passed-with-warnings under ``--mode strict`` · ``1`` usage/internal error.
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import io
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
from xtalate.conversion.batch import RecoveryPresetError, _coerce
from xtalate.discovery import DiscoveryEngine
from xtalate.recovery import RecoveryError
from xtalate.registry import PluginLoadError, default_registry
from xtalate.repair import RepairError, RepairRequest
from xtalate.sdk import AnalysisError, ParseError, run_analysis
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
            "analyze": _cmd_analyze,
            "scenarios": _cmd_scenarios,
        }[args.command]
        return handler(args, registry)
    except AnalysisError as exc:
        # A plugin that broke containment or crashed is a broken plugin, not a graceful refusal:
        # a clean stderr message naming it and exit 1 (§A.2 "usage/internal error"), never a
        # traceback — the run-time analogue of the broken-installed-plugin surface above.
        print(f"error: analysis failed: {exc}", file=sys.stderr)
        return EXIT_USAGE
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
    except RepairError as exc:
        # An invalid --repair (an unknown operation, a malformed spec, or a parameter the
        # operation rejects) is the same caller mistake: clean usage message (exit 1), never a
        # traceback. A *blocked* repair (e.g. a cell-less wrap) is not an error — it refuses
        # through the ordinary refusal path (exit 2) like any recovery the CLI cannot resolve.
        print(f"error: invalid --repair: {exc}", file=sys.stderr)
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


def _writable_extensions(registry: Registry) -> dict[str, list[str]]:
    """``{".ext": [format_id, ...]}`` over **writable** formats only (those with an exporter).
    Extensions are hints declared on the parser (and, if a plugin declares them, the exporter)."""
    writable = {e.format_id for e in registry.exporters()}
    table: dict[str, list[str]] = {}
    plugins: list[Any] = [*registry.parsers(), *registry.exporters()]
    for plugin in plugins:
        if plugin.format_id not in writable:
            continue
        for ext in getattr(plugin, "file_extensions", ()):
            ids = table.setdefault(ext.lower(), [])
            if plugin.format_id not in ids:
                ids.append(plugin.format_id)
    return table


def _infer_target(output: str, registry: Registry) -> str:
    """Infer ``--to`` from the ``-o`` extension when exactly one writable format claims it (Q1).
    Never guesses: zero or several claimants is a usage error that names the candidates (P4)."""
    ext = Path(output).suffix.lower()
    if not ext:
        raise _UsageError(
            f"cannot infer the target format from {output!r} (no extension) — pass --to FORMAT_ID"
        )
    candidates = _writable_extensions(registry).get(ext, [])
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise _UsageError(
            f"no writable format claims the extension {ext!r} — pass --to FORMAT_ID "
            "(see `xtalate capabilities`)"
        )
    options = " or ".join(f"--to {c}" for c in candidates)
    names = " and ".join(candidates)
    raise _UsageError(f"{ext} matches {names} — pass {options}.")


def _frames_repair(spec: str) -> RepairRequest:
    """``--frames`` spec -> a ``select_frames`` repair. ``N`` (no colon) is the single frame N
    (so ``-1`` is the last frame, which is how people read it); anything with a colon is a
    Python slice. A step below 1 is refused here with a message naming the flag."""
    text = spec.strip()
    if not text:
        raise _UsageError("--frames needs START:STOP[:STEP] or an integer N")
    parts = text.split(":")
    if len(parts) > 3:
        raise _UsageError(f"--frames {spec!r} is not START:STOP[:STEP] or an integer N")
    try:
        if len(parts) == 1:
            n = int(parts[0])
            # `-1` is "the last frame": slice(-1, None). Any other N is slice(N, N + 1).
            return RepairRequest(
                operation="select_frames",
                parameters={"start": n, "stop": None if n == -1 else n + 1, "step": 1},
            )
        values = [int(p) if p.strip() else None for p in parts]
    except ValueError:
        raise _UsageError(f"--frames {spec!r} is not START:STOP[:STEP] or an integer N") from None
    step = values[2] if len(values) == 3 and values[2] is not None else 1
    if step < 1:
        raise _UsageError(f"--frames step must be >= 1, got {step}")
    return RepairRequest(
        operation="select_frames",
        parameters={"start": values[0], "stop": values[1], "step": step},
    )


def _dry_run(
    args: argparse.Namespace,
    registry: Registry,
    parsed: Any,
    repairs: list[RepairRequest],
) -> int:
    """``convert --dry-run``: engine pre-flight on the (repaired) parsed object, nothing written."""
    dry = ConversionEngine(registry).dry_run(
        parsed.canonical,
        source_format_id=parsed.format_id,
        target_format_id=args.to,
        source_filename=_source_name(args.file),
        target_filename=Path(args.output).name if args.output else None,
        mode=args.mode,
        repairs=repairs or None,
        parse_issues=list(parsed.issues),
        acknowledge_loss=args.acknowledge_loss,
        acknowledge_parse_warnings=args.acknowledge_parse_warnings,
    )
    if args.report:
        _write_json(args.report, dry.report.model_dump(mode="json"))
    if args.json:
        print(
            _json(
                {
                    "conversion_report": dry.report.model_dump(mode="json"),
                    # Additive key (dry-run only): what each repair would do, with its hazards.
                    "repairs": [
                        {
                            "operation": a.operation,
                            "parameters": a.parameters,
                            "description": a.description,
                            "hazards": [{"code": h.code, "message": h.message} for h in a.hazards],
                        }
                        for a in dry.applied
                    ],
                }
            )
        )
    else:
        print(render.render_dry_run(dry), file=sys.stderr if args.output == "-" else sys.stdout)
    return EXIT_OK if dry.report.status == "completed" else EXIT_REFUSED


_GLOB_CHARS = frozenset("*?[")
_STDIN_NAME = "<stdin>"


def _source_name(file: str) -> str:
    """The ``source_filename`` the reports record: ``<stdin>`` for ``-``, else the basename."""
    return _STDIN_NAME if file == "-" else Path(file).name


def _is_source_directory(path: Path) -> bool:
    """True when ``path`` is a recognised multi-file *source* (a DeePMD-style system) — the
    pre-existing directory-as-input semantics, which win over fan-out so every directory the CLI
    converted before this task still converts identically."""
    return bool(_read_directory(str(path)))


def _expand_inputs(patterns: list[str]) -> tuple[list[Path], bool]:
    """Expand globs the shell left alone and fan out plain directories.

    Returns ``(paths, fan_out)``: ``fan_out`` is True when the request names several files (more
    than one path, or a directory that is not a recognised source). A glob that matches nothing,
    or a directory with nothing to convert, is a usage error."""
    found: list[Path] = []
    fanned = False
    for pattern in patterns:
        path = Path(pattern)
        if any(c in pattern for c in _GLOB_CHARS) and not path.exists():
            matches = [Path(m) for m in sorted(glob.glob(pattern)) if Path(m).is_file()]
            if not matches:
                raise _UsageError(f"{pattern!r} matched no files")
            found.extend(matches)
        elif path.is_dir() and not _is_source_directory(path):
            members = sorted(
                p for p in path.iterdir() if p.is_file() and not p.name.startswith(".")
            )
            if not members:
                raise _UsageError(f"{pattern} contains no files to convert")
            found.extend(members)
            fanned = True
        else:
            found.append(path)
    return found, fanned or len(found) > 1


def _writable_extensions_for(registry: Registry, format_id: str) -> list[str]:
    """The extensions ``format_id`` is written under, sorted: Task 15's ``{ext: [format ids]}``
    table inverted for one format (``[]`` when it declares none, e.g. POSCAR)."""
    return sorted(ext for ext, ids in _writable_extensions(registry).items() if format_id in ids)


def _cmd_convert(args: argparse.Namespace, registry: Registry) -> int:
    inputs: list[str] = list(args.file or [])
    if args.batch:
        if inputs:
            raise _UsageError("convert takes FILE *or* --batch MANIFEST, not both")
        return _cmd_convert_batch(args, registry)
    if not inputs:
        raise _UsageError("convert needs FILE (or --batch MANIFEST)")
    if args.dry_run and args.recover:
        raise _UsageError(
            "--dry-run cannot be combined with --recover: a dry run reports the recovery choices "
            "a real run would ask for and never applies one (drop --recover, or drop --dry-run)"
        )
    if args.dry_run and args.validation_report:
        raise _UsageError(
            "--dry-run runs no validation, so --validation-report has nothing to write"
        )
    to_stdout = args.output == "-"
    if to_stdout and args.json:
        raise _UsageError("--json cannot be combined with -o - (both would use stdout)")
    stdin_mode = inputs == ["-"]
    if "-" in inputs and not stdin_mode:
        raise _UsageError("'-' (stdin) cannot be combined with other inputs")
    if stdin_mode and not args.format:
        raise _UsageError("reading stdin needs --from FORMAT_ID (there is no filename to sniff)")
    if stdin_mode:
        args.file = "-"
    else:
        paths, fan_out = _expand_inputs(inputs)
        if fan_out:
            if to_stdout:
                raise _UsageError("-o - writes one file to stdout; give a single input")
            return _convert_many(args, registry, paths)
        args.file = str(paths[0])
    if args.to is None and args.output and not to_stdout:
        args.to = _infer_target(args.output, registry)
    if args.to is None:
        raise _UsageError(
            "convert needs --to FORMAT_ID or an -o path whose extension names one "
            "(in batch mode the manifest carries it)"
        )
    is_directory = args.file != "-" and Path(args.file).is_dir()
    result = None if is_directory else _convert_streamed(args, registry)
    streamed = result is not None
    if result is None:
        directory_files = _read_directory(args.file) if is_directory else None
        data = None if is_directory else _read_bytes(args.file)
        tolerance = _resolve_tolerance(args.tolerance_profile)
        recovery_choices = _parse_recover(args.recover)
        _inject_references(registry, recovery_choices)
        # User-requested repairs (v1.7 M66; D255): the ordered list is parsed once, up front,
        # and applied by the engine between parse and pre-flight — see the engine-call below.
        repairs = _parse_repair(args.repair)
        if args.frames is not None:
            # Appended LAST so an explicit --repair list keeps its order.
            repairs = [*repairs, _frames_repair(args.frames)]
        # parse-time recovery (missing_species / truncate_corrupt_tail) is applied here, before the
        # engine, if a matching preset was supplied; otherwise the recoverable parse error stands.
        parsed = parse_with_recovery(
            registry,
            data,
            filename=_source_name(args.file),
            format_override=args.format,
            recovery_choices=recovery_choices,
            directory_files=directory_files,
            dirname=Path(args.file).name if is_directory else None,
        )
        if args.dry_run:
            return _dry_run(args, registry, parsed, repairs)
        result = ConversionEngine(registry).convert(
            parsed.canonical,
            source_format_id=parsed.format_id,
            target_format_id=args.to,
            source_filename=_source_name(args.file),
            target_filename=Path(args.output).name if args.output else None,
            mode=args.mode,
            recovery_choices=recovery_choices,
            parse_recovery=parsed,
            repairs=repairs,
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
        say = sys.stderr if to_stdout else sys.stdout
        print(render.render_conversion(report), file=say)
        guidance = render.render_recovery_guidance(report)
        if guidance:
            print(guidance, file=say)
        if result.validation is not None:
            print(file=say)
            print(render.render_validation(result.validation), file=say)

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


def _status_word(report: dict[str, Any], validation: dict[str, Any] | None) -> str:
    """The one-word per-file outcome used in the fan-out summary line."""
    if report["stage"] == "preflight":  # --dry-run
        return "would complete" if report["status"] == "completed" else "needs recovery"
    if report["status"] == "refused":
        return "refused"
    if validation is not None and validation["status"] == "failed":
        return "validation failed"
    if validation is not None and validation["status"] == "passed_with_warnings":
        return "completed with warnings"
    return "completed"


def _convert_one_quiet(
    args: argparse.Namespace, registry: Registry
) -> tuple[int, dict[str, Any] | None, dict[str, Any] | None, str]:
    """Run one fan-out member through the single-file path with its output captured.

    Returns ``(exit_code, conversion_report, validation_report, status_text)``. Per-file caller
    mistakes and parse errors become a line and an exit code rather than ending the run."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _cmd_convert(args, registry)
    except ParseError as exc:
        issue = exc.issues[0] if exc.issues else None
        detail = f" [{issue.code}]: {issue.message}" if issue is not None else ""
        return EXIT_PARSE_ERROR, None, None, f"parse error{detail}"
    except (RepairError, RecoveryError, RecoveryPresetError, _UsageError) as exc:
        return EXIT_USAGE, None, None, f"error: {exc}"
    payload = json.loads(out.getvalue())
    report = payload["conversion_report"]
    validation = payload.get("validation_report")
    return code, report, validation, _status_word(report, validation)


def _convert_many(args: argparse.Namespace, registry: Registry, inputs: list[Path]) -> int:
    """Convert each input into ``-o DIR`` as ``<stem>.<ext>``: one summary line per file, the
    process exit code the highest per-file code. Collisions refuse up front (never an overwrite);
    a per-file failure is a line, not a crash."""
    if not args.output:
        raise _UsageError("converting several inputs needs -o DIR (and --to FORMAT_ID)")
    if args.to is None:
        raise _UsageError(
            "converting several inputs needs --to FORMAT_ID (-o names a directory, which has no "
            "extension to infer the format from)"
        )
    if args.report or args.validation_report:
        raise _UsageError(
            "--report/--validation-report cannot hold several conversions; use --json instead"
        )
    out_dir = Path(args.output)
    if out_dir.exists() and not out_dir.is_dir():
        raise _UsageError(f"-o {args.output!r} exists and is not a directory")
    extension = (_writable_extensions_for(registry, args.to) or ["." + args.to])[0]
    names = [f"{p.stem}{extension}" for p in inputs]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise _UsageError(
            f"several inputs would write the same output name {duplicated}; rename an input or "
            "convert them separately"
        )
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    codes: list[int] = []
    results: list[dict[str, Any]] = []
    for path, name in zip(inputs, names, strict=True):
        sub = argparse.Namespace(
            **{
                **vars(args),
                "file": [str(path)],
                "output": str(out_dir / name),
                "json": True,
                "no_bell": True,
            }
        )
        code, report, validation, status = _convert_one_quiet(sub, registry)
        codes.append(code)
        results.append(
            {
                "input": str(path),
                "output": None if args.dry_run else str(out_dir / name),
                "exit_code": code,
                "status": status,
                "conversion_report": report,
                "validation_report": validation,
            }
        )
        if not args.json:
            print(f"{path.name} -> {name}  {status}")
    if args.json:
        print(_json(results))
    _ring_completion_bell(args)
    return max(codes, default=EXIT_OK)


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
    if args.output == "-":
        raise _UsageError("--batch writes files under -o; it cannot write to stdout (-o -)")
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
    if args.repair:
        # Per-file repairs are a v1.8+ batch question (impl-plan §4.4); M66 wires
        # single-file repair only, so --repair is refused in batch mode like any
        # shared setting the manifest does not carry.
        conflicts.append("--repair")
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
    if args.frames is not None:
        conflicts.append("--frames")
    if args.dry_run:
        conflicts.append("--dry-run")
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
    if not args.output or args.output == "-" or args.file == "-" or args.mode == "strict":
        return None
    if args.repair or args.frames is not None or args.dry_run:
        # --frames is a select_frames repair, and --dry-run must never run the writing streaming
        # engine. Repairs run on the materialized path only: the streaming engines predate v1.7
        # repairs and are frozen for M66 (the one permitted engine-call change is the
        # `repairs=` argument on the materialized `convert`). Routing here is CLI logic.
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


def _cmd_scenarios(args: argparse.Namespace, registry: Registry) -> int:
    from xtalate.cli.render import _offered_choices
    from xtalate.recovery.scenarios import (
        SCENARIO_HAZARD,
        describe_choice,
        describe_scenario,
    )

    names = list(SCENARIO_HAZARD)
    if args.scenario:
        if args.scenario not in SCENARIO_HAZARD:
            raise _UsageError(
                f"unknown scenario {args.scenario!r}; known scenarios: {sorted(SCENARIO_HAZARD)}"
            )
        names = [args.scenario]
    if args.json:
        payload = {
            name: {
                "hazard_class": SCENARIO_HAZARD[name].value,
                "description": describe_scenario(name),
                "choices": {c: describe_choice(name, c) for c in _offered_choices(name)},
            }
            for name in names
        }
        print(_json(payload))
    else:
        print(render.render_scenarios(names))
    return EXIT_OK


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


def _cmd_analyze(args: argparse.Namespace, registry: Registry) -> int:
    """Run one installed analysis plugin against a file and render its namespaced results.

    The CLI mirror of ``POST /v1/analyze`` (M70): one engine (:func:`run_analysis`), two
    presenters. The plugin is looked up by ``name`` in the registry — an unknown name is a caller
    mistake that names the installed set (exit 1), not a refusal; a plugin that breaks containment
    raises :class:`AnalysisError`, handled centrally (exit 1). The results shown are exactly the
    keys the plugin wrote (``run.entries``), the same derivation the HTTP job uses so the two
    surfaces can never drift.
    """
    installed = {plugin.name: plugin for plugin in registry.analysis_plugins()}
    plugin = installed.get(args.plugin)
    if plugin is None:
        names = ", ".join(sorted(installed)) or "(none installed)"
        raise _UsageError(
            f"unknown analysis plugin {args.plugin!r}; installed analysis plugins: {names} "
            "(see `xtalate capabilities` or the plugins endpoint for the full roster)"
        )
    data = _read_bytes(args.file)
    canonical, _fmt = _parse_source(registry, data, args.file, args.format)
    # ``results`` is exactly the plugin's own entries (v2.0 S6, D294): re-scanning the merged
    # ``custom_global`` by prefix would mis-attribute a pre-existing carry-through key sharing the
    # plugin's namespace as plugin output. This is the same derivation the HTTP job uses.
    results = run_analysis(canonical, plugin).entries
    if args.json:
        print(_json({"plugin": plugin.name, "version": plugin.version, "results": results}))
    else:
        print(render.render_analysis(plugin.name, plugin.version, results))
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


def _parse_repair(specs: list[str] | None) -> list[RepairRequest]:
    """Parse repeated ``--repair OPERATION[,param=value…]`` into an ordered ``list[RepairRequest]``.

    ``--repair`` is **order-dependent** on purpose (D255): repeated flags build the request list
    in argument order and the same operation may appear twice — wrap-then-center and
    center-then-wrap are different structures, and the report records which happened. This is
    deliberately **not** the ``--recover`` dict grammar (``parse_recovery_presets``): a
    scenario-keyed dict discards order and forbids the duplicate operations a repair stack
    legitimately needs. Parameter values are coerced with the same scalar coercion ``--recover``
    uses (``distance_threshold=0.05`` is a float, ``target=origin`` a string). The explicit
    ``[x, y, z]`` center target is **not** reachable from the CLI in v1.7 (the coercion is
    scalar-only; bracketed lists are a follow-up) — stated in ``--help``. A malformed spec raises
    ``RepairError``, so the whole class of bad ``--repair`` usage exits 1 through the same
    handler as a parameter the engine rejects; an unknown operation or an incoherent parameter
    surfaces the engine's own ``RepairError`` when ``convert`` applies the list."""
    requests: list[RepairRequest] = []
    for spec in specs or []:
        parts = spec.split(",")
        operation = parts[0].strip()
        if not operation:
            raise RepairError(f"repair {spec!r} must name an operation (OPERATION[,param=value…])")
        parameters: dict[str, Any] = {}
        for param in parts[1:]:
            if "=" not in param:
                raise RepairError(f"--repair parameter {param!r} must be name=value")
            name, value = param.split("=", 1)
            parameters[name] = _coerce(value)
        requests.append(RepairRequest(operation=operation, parameters=parameters))
    return requests


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
    if args.output == "-":
        if result.outputs is not None or result.output_dir is not None:
            raise _UsageError("-o - cannot hold a multi-file output (use -o DIR)")
        if result.output is not None:
            sys.stdout.buffer.write(result.output)
            sys.stdout.buffer.flush()
        return
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
    known = {"type.raw", "type_map.raw", "nopbc"}
    files: dict[str, bytes] = {}
    for child in sorted(root.rglob("*")):
        if not child.is_file():
            continue
        relative = child.relative_to(root).as_posix()
        if relative in known or (relative.startswith("set.") and relative.count("/") == 1):
            files[relative] = _read_bytes(str(child))
    return files


def _read_bytes(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
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
        "file",
        nargs="*",
        metavar="FILE",
        help=(
            "Source file(s), glob(s) or a directory of files to convert into -o DIR; '-' reads "
            "stdin (needs --from). List all inputs before the options. Omit with --batch."
        ),
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
        help="Write the converted file here (a directory when converting several inputs; batch: "
        "a directory for per-file mode, a file for assemble mode). '-' writes the result to "
        "stdout (status goes to stderr; a trajectory is then held in memory).",
    )
    p_convert.add_argument(
        "--format",
        "--from",
        dest="format",
        metavar="FORMAT_ID",
        help="Override source format sniffing (--from is an alias).",
    )
    p_convert.add_argument("--mode", choices=("permissive", "strict"), default="permissive")
    p_convert.add_argument(
        "--recover",
        action="append",
        metavar="SCENARIO=CHOICE[,param=value…]",
        help="Preset recovery choice (repeatable).",
    )
    p_convert.add_argument(
        "--repair",
        action="append",
        metavar="OPERATION[,param=value…]",
        help="Apply a repair operation before export (repeatable; applied in the given "
        "order). Operations: wrap_into_cell (no parameters); center "
        "(reference=centroid|cell_center, target=origin|cell_center); deduplicate "
        "(distance_threshold=ANGSTROM); species_reorder (optional permutation=…); "
        "select_frames (start=,stop=,step=: keep a Python-slice subset of frames). "
        "An explicit-coordinate [x, y, z] center target is not supported on the CLI yet.",
    )
    p_convert.add_argument(
        "--frames",
        metavar="START:STOP[:STEP]|N",
        help=(
            "Keep a Python-slice subset of frames (e.g. 0:100:5, ::2, --frames=-10:); a bare "
            "integer N keeps only frame N (negative counts from the end). Same as --repair "
            "select_frames. Write a leading-minus value with '=' (--frames=-1)."
        ),
    )
    p_convert.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Parse, apply repairs and pre-flight only; write nothing. Exit 0 if the conversion "
            "would run without a recovery choice, 2 if it needs one or would be refused (in --mode "
            "strict the acknowledgement gates are evaluated: pass --acknowledge-loss / "
            "--acknowledge-parse-warnings to see the run as acknowledged). Cannot be combined with "
            "--recover (a dry run reports the choices a real run would ask for)."
        ),
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

    p_analyze = sub.add_parser(
        "analyze", help="Run one installed analysis plugin on a file (annotate its own namespace)."
    )
    p_analyze.add_argument("file")
    p_analyze.add_argument(
        "--plugin",
        required=True,
        metavar="NAME",
        help="Analysis plugin name (an unknown name lists the installed set).",
    )
    p_analyze.add_argument("--format", metavar="FORMAT_ID", help="Override source format sniffing.")
    p_analyze.add_argument(
        "--json", action="store_true", help="Print {plugin, version, results} as JSON."
    )

    p_caps = sub.add_parser("capabilities", help="Print the Capability Matrix.")
    p_caps.add_argument("format_id", nargs="?", metavar="FORMAT_ID", help="Limit to one format.")
    p_caps.add_argument("--json", action="store_true", help="Print the matrix JSON.")

    p_scen = sub.add_parser(
        "scenarios", help="List the recovery scenarios and the choices that resolve them."
    )
    p_scen.add_argument("scenario", nargs="?", metavar="SCENARIO", help="Limit to one scenario.")
    p_scen.add_argument("--json", action="store_true", help="Print the catalog as JSON.")

    return parser


__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover - module-run convenience.
    raise SystemExit(main())
