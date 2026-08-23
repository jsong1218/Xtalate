"""Batch conversion — the aggregate surface (MASTER_SPEC Part 6 preamble; v1.5 M54).

A **wrapper**, not a second engine: :func:`run_batch` resolves a YAML manifest to an ordered
file list, fans each file out to the **ordinary** single-file conversion path
(:func:`xtalate.conversion.parse_with_recovery` + :meth:`ConversionEngine.convert` — the exact
path a lone ``xtalate convert`` takes), and assembles a :class:`BatchReport`. The aggregate
**embeds each per-file ``ConversionReport`` / ``ValidationReport`` verbatim** — the existing
models, unchanged, so the same file converted alone and inside a batch serializes
byte-identically (the machine-checkable form of \"the aggregate cannot elide a per-file loss\",
**P1** at dataset scale). Tallies are **counts, never restatements**: no \"top losses\" digest, no
merged assumption list — that would be a second report schema, the failure the roadmap names (§6).

Failure isolation is structural: one file's parse failure or refusal is **that file's outcome**
(a refusal is a completed conversion, exactly as on the wire since v0.5), never a batch abort.
The batch always returns a complete :class:`BatchReport`; ``fail_fast`` (opt-in, default
``False``) stops at the first non-success for the caller who wants it.

A **dataset is aggregation, not a new model**: ``BatchManifest`` / ``BatchReport`` are
conversion-layer models (they live beside the engine, not in ``schema/``), and this module adds
**zero** canonical schema fields and **zero** ``ParseIssue`` codes. The manifest deliberately has
**no fields** for frame selection by criteria, train/test splitting, or deduplication — selection
and curation are scientific judgments about data, not translations of it (roadmap §11); a
manifest carrying such a key is rejected by ``extra=\"forbid\"`` (the scope refusal, enforced not
merely omitted).
"""

from __future__ import annotations

import glob as _glob
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xtalate._time import utc_now as _utc_now
from xtalate.capabilities import Registry
from xtalate.conversion.engine import ConversionEngine
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.conversion.report import ConversionReport
from xtalate.sdk import ParseError
from xtalate.validation.report import ValidationReport

__all__ = [
    "BatchEntry",
    "BatchError",
    "BatchManifest",
    "BatchManifestError",
    "BatchReport",
    "BatchTallies",
    "LabelPresence",
    "RecoveryPresetError",
    "SourceEntry",
    "SourceOverride",
    "load_manifest",
    "parse_recovery_presets",
    "run_batch",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BatchManifestError(ValueError):
    """A malformed or self-inconsistent batch manifest — a caller mistake, like a bad ``--recover``
    preset on the CLI, surfaced as a usage error (exit 1), never a traceback."""


class RecoveryPresetError(ValueError):
    """A malformed recovery preset string in a manifest (the CLI ``--recover`` grammar)."""


# --- the input model (conversion-layer, not schema/) -----------------------------------------


class SourceOverride(_Model):
    """Per-source override of the shared manifest settings (the cut line: minimal by design).

    Each field replaces the shared value for that one source; ``recovery_choices`` *replaces*
    (never merges) the shared preset list. Breadth is cuttable; the mechanism is not.
    """

    mode: Literal["permissive", "strict"] | None = None
    recovery_choices: list[str] | None = None
    tolerance_profile: str | None = None
    acknowledge_loss: bool | None = None
    acknowledge_parse_warnings: bool | None = None


class SourceEntry(_Model):
    """One manifest source: a literal path **or** a glob pattern (resolved deterministically,
    recorded in the report). Manifest order is processing order **and** report order."""

    path: str
    override: SourceOverride | None = None


class BatchManifest(_Model):
    """The batch input: an ordered source list, **one** target, shared settings, optional
    per-source overrides. YAML in, this model out (``load_manifest``).

    ``sources`` accepts either a plain path/glob string or ``{path, override}``. No fields for
    selection / splitting / deduplication — their presence is rejected (the scope refusal).
    """

    sources: list[SourceEntry | str]
    target: str
    output_mode: Literal["per-file", "assemble"] = "per-file"
    mode: Literal["permissive", "strict"] = "permissive"
    # The CLI ``--recover`` preset grammar, one string per preset (``reuse`` the existing parser,
    # never a second grammar): ``SCENARIO=CHOICE[,param=value…]``.
    recovery_choices: list[str] = Field(default_factory=list)
    tolerance_profile: str = "default"
    acknowledge_loss: bool = False
    acknowledge_parse_warnings: bool = False


def load_manifest(path: str | Path) -> BatchManifest:
    """Read and validate a YAML batch manifest. A malformed document or an unknown key raises
    ``BatchManifestError`` (a caller mistake), never a partial run."""
    import yaml

    try:
        text = Path(path).read_text()
    except OSError as exc:
        raise BatchManifestError(f"cannot read manifest {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise BatchManifestError(f"malformed manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BatchManifestError(f"manifest {path} must be a YAML mapping")
    try:
        return BatchManifest.model_validate(data)
    except Exception as exc:  # pydantic ValidationError (incl. unknown keys); normalise
        raise BatchManifestError(f"invalid manifest {path}: {exc}") from exc


# --- the aggregate model (conversion-layer, not schema/) -------------------------------------


class BatchError(_Model):
    """The structured record of a per-file *failure* (a parse error): the terminal outcome of a
    file that produced no conversion at all. A refusal is *not* an error — it is a completed
    conversion whose report says so."""

    code: str
    message: str


class BatchEntry(_Model):
    """One resolved source's terminal outcome, embedding that file's ``ConversionReport`` and —
    when validation ran — its ``ValidationReport`` **verbatim** (the existing models, unchanged).
    ``conversion`` is ``None`` only for a parse *failure* (no conversion could start)."""

    source: str  # The resolved source path (the concrete file that ran).
    status: Literal["converted", "refused", "failed"]
    conversion: ConversionReport | None = None
    validation: ValidationReport | None = None
    error: BatchError | None = None


class LabelPresence(_Model):
    """How many converted files contributed each MLIP label to the outputs — counts only, derived
    from the per-file objects' ``preserved`` paths (a label is contributed iff the target wrote
    it, i.e. its canonical path survived the conversion). Never a restatement of per-file loss."""

    energy: int = 0
    forces: int = 0
    stress: int = 0


class BatchTallies(_Model):
    """Dataset-level counts. **Counts, never restatements** — no merged assumptions, no \"top
    losses\" digest (that is the second-report-schema failure mode)."""

    total: int
    converted: int
    refused: int
    failed: int
    label_presence: LabelPresence


class BatchReport(_Model):
    """The aggregate record: the resolved manifest (reproducible), the per-file entries with the
    existing reports embedded verbatim, and the tallies. ``note`` carries the dataset-level
    variable-N statement for an assembled artifact (M54-S2) — a property of the assembled file,
    never a per-file loss."""

    report_id: str
    created_at: str  # ISO 8601 UTC.
    manifest: BatchManifest  # The *resolved* manifest: concrete file list, settings.
    entries: list[BatchEntry] = Field(default_factory=list)
    tallies: BatchTallies
    note: str | None = None


# --- the `--recover` preset grammar (one implementation, shared with the CLI) -----------------


def _coerce(value: str) -> Any:
    """Coerce a preset parameter string to int, then float, else leave it a string."""
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def parse_recovery_presets(specs: list[str] | None) -> dict[str, dict[str, Any]]:
    """Parse ``SCENARIO=CHOICE[,param=value…]`` preset strings into the engine's
    ``recovery_choices`` structure.

    This is the CLI ``--recover`` grammar (``cli/main.py``) — the manifest's shared
    ``recovery_choices`` and per-source overrides carry the same strings, and the CLI (M54-S3)
    consumes this same function, so the batch never invents a second preset grammar. A malformed
    string raises :class:`RecoveryPresetError` — a caller mistake, like a bad ``--recover`` on
    the CLI.
    """
    choices: dict[str, dict[str, Any]] = {}
    for spec in specs or []:
        if "=" not in spec:
            raise RecoveryPresetError(
                f"recovery preset {spec!r} must be SCENARIO=CHOICE[,param=value…]"
            )
        scenario, rest = spec.split("=", 1)
        parts = rest.split(",")
        choice = parts[0]
        params: dict[str, Any] = {}
        for param in parts[1:]:
            if "=" not in param:
                raise RecoveryPresetError(f"recovery preset parameter {param!r} must be name=value")
            name, value = param.split("=", 1)
            params[name] = _coerce(value)
        choices[scenario] = {"choice": choice, "parameters": params}
    return choices


# --- the orchestrator ------------------------------------------------------------------------


#: Canonical paths whose survival means the converted output carries the MLIP label (written by
#: an extXYZ-family target, Part 2 §3.7). Label-presence tallies derive from these.
_LABEL_PATHS: dict[str, str] = {
    "energy": "electronic.total_energy",
    "forces": "dynamics.forces",
    "stress": "electronic.stress",
}

#: The single-structure targets whose outputs conventionally take no extension (Part 4 §3.3's
#: split-output naming, mirrored here so a batch and a lone convert name files alike).
_NO_SUFFIX_TARGETS = frozenset({"poscar", "contcar"})


def run_batch(
    manifest: BatchManifest,
    registry: Registry,
    *,
    output: str | Path | None = None,
    fail_fast: bool = False,
) -> BatchReport:
    """Run a batch manifest to a complete :class:`BatchReport`.

    Resolves the manifest's sources deterministically (globs sorted; the concrete list recorded in
    the report), then converts each file through the **ordinary** single-file path — the same
    ``parse_with_recovery`` + :meth:`ConversionEngine.convert` a lone ``xtalate convert`` takes;
    the batch re-implements none of the convert path. **Failure isolation:** a per-file parse
    error or refusal becomes that entry's outcome and the loop continues; the batch always
    returns a complete report. ``fail_fast=True`` (surfaced as ``--fail-fast``) stops at the first
    non-``converted`` entry.

    ``output``: in ``per-file`` mode a directory (created) receiving one file per converted
    source, named ``<stem>.<target>`` (no suffix for POSCAR/CONTCAR); in ``assemble`` mode the
    path of the one multi-frame artifact. ``None`` runs the conversions and produces the report
    without writing artifacts. A caller mistake (unknown target, malformed preset, empty source
    list, a glob matching nothing, a missing literal path, a per-file output-name collision, or
    ``assemble`` to a non-append-capable target) raises :class:`BatchManifestError` before any
    file is converted. A genuinely broken conversion (an engine invariant failure) propagates —
    never swallowed into a batch that looks green.
    """
    target = manifest.target
    if target not in {e.format_id for e in registry.exporters()}:
        known = ", ".join(sorted(e.format_id for e in registry.exporters()))
        raise BatchManifestError(f"unknown target format {target!r}; known targets: {known}")

    shared_choices = parse_recovery_presets(manifest.recovery_choices)
    resolved = _resolve_sources(manifest)
    if not resolved:
        raise BatchManifestError("manifest sources resolved to no files")

    if manifest.output_mode == "assemble":
        # M54-S2 wires the second output mode (append N sources → one artifact); S1 accepts
        # only per-file, and a manifest asking for assemble is a clear refusal, never a silent
        # fallback to per-file.
        raise BatchManifestError(
            "assemble output mode is not yet available (M54-S2); use output_mode: per-file"
        )
    return _run_per_file(
        manifest, resolved, shared_choices, registry, output=output, fail_fast=fail_fast
    )


def _resolve_sources(manifest: BatchManifest) -> list[SourceEntry]:
    """Expand ``sources`` to a concrete, deterministic file list (globs sorted; recorded order =
    manifest order = processing/report order). A glob that matches nothing or a literal path that
    does not exist is a caller mistake, raised before any file is converted."""
    resolved: list[SourceEntry] = []
    for source in manifest.sources:
        entry = source if isinstance(source, SourceEntry) else SourceEntry(path=source)
        if _glob.has_magic(entry.path):
            matches = sorted(_glob.glob(entry.path))
            if not matches:
                raise BatchManifestError(f"glob {entry.path!r} matched no files")
            resolved.extend(SourceEntry(path=match, override=entry.override) for match in matches)
        else:
            if not Path(entry.path).is_file():
                raise BatchManifestError(f"source {entry.path!r} does not exist")
            resolved.append(entry)
    return resolved


def _run_per_file(
    manifest: BatchManifest,
    resolved: list[SourceEntry],
    shared_choices: dict[str, dict[str, Any]],
    registry: Registry,
    *,
    output: str | Path | None,
    fail_fast: bool,
) -> BatchReport:
    planned = {_output_name(e.path, manifest.target) for e in resolved}
    if len(planned) != len(resolved):
        raise BatchManifestError(
            "per-file output names collide for the resolved sources (two sources share a stem); "
            "rename a source or split the batch"
        )
    out_dir = Path(output) if output is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    engine = ConversionEngine(registry)
    entries: list[_Outcome] = []
    for entry in resolved:
        outcome = _convert_one(engine, registry, entry, manifest, shared_choices)
        entries.append(outcome)
        _write_per_file_outputs(out_dir, entry, outcome, manifest.target)
        if fail_fast and outcome.entry.status != "converted":
            break
    return _assemble_report(manifest, resolved, entries, note=None)


# The reported per-file entry plus the raw outputs the orchestrator needs while the run is in
# flight — deliberately **not** a report model: the raw bytes must never leak into the
# serialized ``BatchReport`` (the report embeds the existing report models verbatim and nothing
# else), so ``_assemble_report`` drops this holder and keeps only its ``entry``.
@dataclass
class _Outcome:
    entry: BatchEntry
    output_bytes: list[bytes] = field(default_factory=list)


def _convert_one(
    engine: ConversionEngine,
    registry: Registry,
    entry: SourceEntry,
    manifest: BatchManifest,
    shared_choices: dict[str, dict[str, Any]],
) -> _Outcome:
    """Convert one resolved source through the ordinary single-file path; **never** let its
    failure abort the batch. A ``ParseError`` is that file's ``failed`` outcome; a ``refused``
    conversion is a completed outcome (its report embedded verbatim); a caller mistake in the
    presets raises (it would fail every file — a manifest error, not a data failure); an engine
    invariant failure propagates."""
    override = entry.override
    mode = override.mode if override and override.mode else manifest.mode
    tolerance = (
        override.tolerance_profile
        if override and override.tolerance_profile
        else manifest.tolerance_profile
    )
    acknowledge_loss = (
        override.acknowledge_loss
        if override and override.acknowledge_loss is not None
        else manifest.acknowledge_loss
    )
    acknowledge_parse_warnings = (
        override.acknowledge_parse_warnings
        if override and override.acknowledge_parse_warnings is not None
        else manifest.acknowledge_parse_warnings
    )
    choices = (
        parse_recovery_presets(override.recovery_choices)
        if override and override.recovery_choices is not None
        else shared_choices
    )
    target_filename = _output_name(entry.path, manifest.target)
    try:
        data = Path(entry.path).read_bytes()
    except OSError as exc:
        return _failed(entry, "SOURCE_UNREADABLE", f"cannot read {entry.path}: {exc}")
    try:
        parsed = parse_with_recovery(
            registry,
            data,
            filename=Path(entry.path).name,
            recovery_choices=choices,
        )
        result = engine.convert(
            parsed.canonical,
            source_format_id=parsed.format_id,
            target_format_id=manifest.target,
            source_filename=Path(entry.path).name,
            target_filename=target_filename,
            mode=mode,
            recovery_choices=choices,
            parse_recovery=parsed,
            acknowledge_loss=acknowledge_loss,
            acknowledge_parse_warnings=acknowledge_parse_warnings,
            tolerance_profile=tolerance,
        )
    except ParseError as exc:
        issue = exc.issues[0] if exc.issues else None
        return _failed(
            entry,
            issue.code if issue else "PARSE_ERROR",
            issue.message if issue else str(exc),
        )
    if result.report.status == "refused":
        return _Outcome(
            entry=BatchEntry(source=entry.path, status="refused", conversion=result.report)
        )
    # `result.outputs` is set iff frame_selection=split_all resolved (one file per frame);
    # `result.output` carries the ordinary single-file bytes. Both are per-source outputs.
    bytes_out = (
        list(result.outputs)
        if result.outputs is not None
        else ([result.output] if result.output is not None else [])
    )
    return _Outcome(
        entry=BatchEntry(
            source=entry.path,
            status="converted",
            conversion=result.report,
            validation=result.validation,
        ),
        output_bytes=bytes_out,
    )


def _failed(entry: SourceEntry, code: str, message: str) -> _Outcome:
    return _Outcome(
        entry=BatchEntry(
            source=entry.path,
            status="failed",
            conversion=None,
            validation=None,
            error=BatchError(code=code, message=message),
        )
    )


def _write_per_file_outputs(
    out_dir: Path | None, entry: SourceEntry, outcome: _Outcome, target: str
) -> bool:
    """Write one converted source's outputs into ``out_dir`` (per-file mode). A ``split_all``
    result (multiple frames) lands in a ``<stem>.split/`` subdirectory, mirroring the single-file
    CLI's split-output convention; nothing is written for refused/failed entries. Returns whether
    anything was written."""
    if out_dir is None or outcome.entry.status != "converted" or not outcome.output_bytes:
        return False
    if len(outcome.output_bytes) == 1:
        (out_dir / _output_name(entry.path, target)).write_bytes(outcome.output_bytes[0])
        return True
    # frame_selection=split_all: one file per frame, in a <stem>.split/ subdirectory — the
    # single-file CLI's split-output convention, mirrored so a batch names frames alike.
    split_dir = out_dir / f"{Path(entry.path).stem}.split"
    split_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if target in _NO_SUFFIX_TARGETS else f".{target}"
    for i, chunk in enumerate(outcome.output_bytes):
        (split_dir / f"frame_{i:04d}{suffix}").write_bytes(chunk)
    return True


def _assemble_report(
    manifest: BatchManifest,
    resolved: list[SourceEntry],
    entries: list[_Outcome],
    *,
    note: str | None,
) -> BatchReport:
    # Keep only the report models — the raw bytes holder never reaches the serialized report.
    reported = [o.entry for o in entries]
    converted = [e for e in reported if e.status == "converted"]
    refused = [e for e in reported if e.status == "refused"]
    failed = [e for e in reported if e.status == "failed"]
    presence = LabelPresence()
    for entry in converted:
        if entry.conversion is None:
            continue
        preserved = {e.path for e in entry.conversion.preserved}
        for label, path in _LABEL_PATHS.items():
            if path in preserved:
                setattr(presence, label, getattr(presence, label) + 1)
    resolved_manifest = manifest.model_copy(
        update={"sources": [SourceEntry(path=e.path, override=e.override) for e in resolved]}
    )
    return BatchReport(
        report_id=str(uuid.uuid4()),
        created_at=_utc_now(),
        manifest=resolved_manifest,
        entries=reported,
        tallies=BatchTallies(
            total=len(entries),
            converted=len(converted),
            refused=len(refused),
            failed=len(failed),
            label_presence=presence,
        ),
        note=note,
    )


def _output_name(source_path: str, target: str) -> str:
    """The per-file output filename for one source: its stem plus the target's conventional
    extension (POSCAR/CONTCAR take none, mirroring the single-file CLI)."""
    stem = Path(source_path).stem
    suffix = "" if target in _NO_SUFFIX_TARGETS else f".{target}"
    return f"{stem}{suffix}"
