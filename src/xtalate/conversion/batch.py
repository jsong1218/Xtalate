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
import io
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xtalate._time import utc_now as _utc_now
from xtalate.capabilities import Registry
from xtalate.conversion.engine import ConversionEngine
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.conversion.report import ConversionReport
from xtalate.sdk import AssembleContribution, ParseError
from xtalate.validation.report import ValidationReport

if TYPE_CHECKING:
    from xtalate.schema import CanonicalObject

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

#: The row-qualified source label a fanned-out multi-structure container row carries in its
#: ``BatchEntry.source`` (and its output stem): ``<container path>::row=<i>``. The separator is a
#: batch-module contract — ``cli/main.py``'s exit-code fold strips it to recover the container's
#: per-source override (M55-S3). Kept off the ``__all__`` surface; a helper reads it.
_ROW_LABEL_SEP = "::row="

#: The row-count grammar the ``ase_db`` parser stamps on its ``ASEDB_MULTIPLE_ROWS`` refusal
#: (``location="rows N"``, mirrored from ``parsers.ase_db._ROW_COUNT_LOCATION``). The fan-out
#: reads N from it rather than parsing the refusal's prose, so a multi-row container expands to
#: exactly its row count (M55-S3).
_ROW_COUNT_LOCATION = re.compile(r"^rows (\d+)$")


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
    ``assemble`` to a non-assemble-capable target) raises :class:`BatchManifestError` before any
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
        _assert_assemble_capable(registry, target)
        return _run_assemble(
            manifest, resolved, shared_choices, registry, output=output, fail_fast=fail_fast
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


def _assert_assemble_capable(registry: Registry, target: str) -> None:
    """The ``assemble`` gate: the target must **declare** that it can combine N Canonical Objects
    into one dataset container (``FormatCapabilities.assemble_capable``, M55-S4/D208) — the exporter
    overrides :meth:`ExporterPlugin.assemble`. A **declared** capability, not a hardcoded target
    list: extXYZ (concatenated multi-frame blocks) and ASE ``.db`` (appended rows) both declare it,
    and a new dataset container rides the same seam (P6). A target that does not declare it is
    refused here — before any file is converted — never silently downgraded to per-file."""
    caps = registry.capability_matrix().get(target, "write")
    if not caps.assemble_capable:
        raise BatchManifestError(
            f"assemble is not available for target {target!r}: it is not an assemble-capable "
            "target — its outputs cannot be combined into one dataset container "
            "(use output_mode: per-file)"
        )


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
    stopped = False
    for entry in resolved:
        # One source yields one outcome — or, for a multi-structure container (a multi-row `.db`),
        # N per-row outcomes fanned out lazily so ``fail_fast`` can stop mid-container (M55-S3).
        for outcome in _convert_source(engine, registry, entry, manifest, shared_choices):
            entries.append(outcome)
            _write_per_file_outputs(out_dir, outcome, manifest.target)
            if fail_fast and outcome.entry.status != "converted":
                stopped = True
                break
        if stopped:
            break
    return _assemble_report(manifest, resolved, entries, note=None)


# The reported per-file entry plus the raw outputs/atom count the orchestrator needs while the
# run is in flight — deliberately **not** a report model: the raw bytes must never leak into the
# serialized ``BatchReport`` (the report embeds the existing report models verbatim and nothing
# else), so ``_assemble_report`` drops this holder and keeps only its ``entry``.
@dataclass
class _Outcome:
    entry: BatchEntry
    output_bytes: list[bytes] = field(default_factory=list)
    canonical_atom_count: int | None = None
    # The stem the per-file writer names this outcome's output after: the source stem, or a
    # row-qualified ``<stem>.row<NNNN>`` for a fanned-out container row (M55-S3), so N rows of one
    # `.db` write N distinct files rather than overwriting one.
    output_stem: str = ""
    # The write-plan-filtered object the engine exported for this source (``canonical_out``),
    # retained so the ``assemble`` combine can rebuild a container (a ``.db`` row) that cannot be
    # produced by byte-concatenation (M55-S4). Never serialized — same discipline as
    # ``output_bytes``: ``_assemble_report`` drops this holder and keeps only ``entry``.
    canonical: CanonicalObject | None = None


def _convert_source(
    engine: ConversionEngine,
    registry: Registry,
    entry: SourceEntry,
    manifest: BatchManifest,
    shared_choices: dict[str, dict[str, Any]],
) -> Iterator[_Outcome]:
    """Yield the outcome(s) for one resolved source, lazily (M55-S3, D207).

    An ordinary source (or a single-row `.db`, or a `.db` for which the caller already pinned one
    row via ``asedb_row_selection=index``) is one outcome. A **multi-structure container** — a
    `.db` with more than one row — refuses ``ASEDB_MULTIPLE_ROWS`` on the single-file path, and the
    batch surface is exactly where its rows convert: it **fans out** to N ordinary per-row
    conversions, each an explicit ``asedb_row_selection=index,row=i`` choice (P4), each its own
    ``BatchEntry`` with a ``<path>::row=<i>`` label. A **dataset is aggregation, not a new model**
    (Part 2 §3.2): the rows never become one Canonical Object. Lazy so ``fail_fast`` stops
    mid-container — the consumer breaks and the remaining rows are never converted."""
    outcome = _convert_one(engine, registry, entry, manifest, shared_choices)
    if not _is_multi_row_refusal(outcome):
        yield outcome
        return
    count = _fanout_row_count(registry, entry)
    if count is None:
        # Defensive: the refusal named a count we could not read — surface it as the ordinary
        # per-file failure rather than silently dropping the source (never a phantom green batch).
        yield outcome
        return
    for row in range(count):
        yield _convert_one(engine, registry, entry, manifest, shared_choices, row=row)


def _is_multi_row_refusal(outcome: _Outcome) -> bool:
    """True iff this source failed the single-file path *only* because it is a multi-structure
    container (a multi-row ASE `.db`) — the one failure the batch resolves by fan-out rather than
    reporting. Any other parse failure stays that source's ``failed`` outcome."""
    return (
        outcome.entry.status == "failed"
        and outcome.entry.error is not None
        and outcome.entry.error.code == "ASEDB_MULTIPLE_ROWS"
    )


def _fanout_row_count(registry: Registry, entry: SourceEntry) -> int | None:
    """The authoritative row count for a multi-structure container, read from the
    ``ASEDB_MULTIPLE_ROWS`` refusal's ``location="rows N"`` by parsing with **no** row-selection
    preset (which surfaces the refusal verbatim). ``None`` when the source does not refuse that way
    — it is then not a container to fan out."""
    try:
        data = Path(entry.path).read_bytes()
    except OSError:
        return None
    try:
        parse_with_recovery(registry, data, filename=Path(entry.path).name, recovery_choices={})
    except ParseError as exc:
        for issue in exc.issues:
            if issue.code == "ASEDB_MULTIPLE_ROWS" and issue.location:
                match = _ROW_COUNT_LOCATION.match(issue.location)
                if match:
                    return int(match.group(1))
    return None


def _run_assemble(
    manifest: BatchManifest,
    resolved: list[SourceEntry],
    shared_choices: dict[str, dict[str, Any]],
    registry: Registry,
    *,
    output: str | Path | None,
    fail_fast: bool,
) -> BatchReport:
    """The ``assemble`` output mode: N sources → **one** dataset container via the target's
    **declared assemble capability** (M55-S4/D208). Each file converts through the ordinary path;
    its write-plan-filtered object and output bytes become one contribution, and the target's
    :meth:`ExporterPlugin.assemble` combines them — extXYZ concatenates the per-source bytes
    (byte-identical to M54), ASE ``.db`` appends one row per object. The batch layer holds no
    per-format combine logic (P2): it collects contributions and hands them to the exporter.

    **Per-contribution validation** stays per source: each entry's ``ValidationReport`` is the
    re-parse-and-diff of *that source's own output* against its own Canonical Object — exactly what
    the per-file conversion validated, so the report keeps its meaning for every file. The
    assembled *whole* is never the validation unit: a mixed-composition extXYZ artifact is a valid
    MLIP training file but **not** one Canonical Object (Part 2 §3.2), which the dataset-level note
    states rather than hiding."""
    engine = ConversionEngine(registry)
    entries: list[_Outcome] = []
    contributions: list[AssembleContribution] = []
    atom_counts: dict[str, int] = {}
    stopped = False
    for entry in resolved:
        # Fan a multi-structure container out to its rows (M55-S3); each row joins the assembled
        # container in row order, keyed by its ``<path>::row=<i>`` label so a fanned container of
        # mixed composition surfaces variable-N like any other source mix.
        for outcome in _convert_source(engine, registry, entry, manifest, shared_choices):
            entries.append(outcome)
            if outcome.entry.status == "converted" and outcome.canonical is not None:
                contributions.append(
                    AssembleContribution(
                        canonical=outcome.canonical, output=list(outcome.output_bytes)
                    )
                )
                if outcome.canonical_atom_count is not None:
                    atom_counts[outcome.entry.source] = outcome.canonical_atom_count
            if fail_fast and outcome.entry.status != "converted":
                stopped = True
                break
        if stopped:
            break
    assembled = b""
    if contributions:
        buf = io.BytesIO()
        registry.get_exporter(manifest.target).assemble(contributions, buf)
        assembled = buf.getvalue()
    note = _assembled_note(registry, manifest.target, assembled, atom_counts)
    if output is not None and assembled:
        Path(output).write_bytes(assembled)
    return _assemble_report(manifest, resolved, entries, note=note)


def _convert_one(
    engine: ConversionEngine,
    registry: Registry,
    entry: SourceEntry,
    manifest: BatchManifest,
    shared_choices: dict[str, dict[str, Any]],
    *,
    row: int | None = None,
) -> _Outcome:
    """Convert one resolved source through the ordinary single-file path; **never** let its
    failure abort the batch. A ``ParseError`` is that file's ``failed`` outcome; a ``refused``
    conversion is a completed outcome (its report embedded verbatim); a caller mistake in the
    presets raises (it would fail every file — a manifest error, not a data failure); an engine
    invariant failure propagates.

    ``row`` (M55-S3) pins one row of a multi-structure container: the ordinary path runs with an
    added ``asedb_row_selection=index,row=<row>`` choice, and the outcome carries a
    ``<path>::row=<row>`` source label + a ``<stem>.row<NNNN>`` output stem so N rows of one `.db`
    are N independent, individually-reported conversions. ``None`` is the ordinary single-source
    path (its stem is the source stem, its label the source path)."""
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
    label = _source_label(entry.path, row)
    stem = _row_stem(entry.path, row)
    if row is not None:
        # Fan-out pins exactly this row: the ``asedb_row_selection=index`` choice overrides any
        # row selection the manifest carried, so a container's rows convert one apiece (M55-S3).
        choices = {
            **choices,
            "asedb_row_selection": {"choice": "index", "parameters": {"row": row}},
        }
    target_filename = _output_name_for(stem, manifest.target)
    try:
        data = Path(entry.path).read_bytes()
    except OSError as exc:
        return _failed(label, "SOURCE_UNREADABLE", f"cannot read {entry.path}: {exc}")
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
            label,
            issue.code if issue else "PARSE_ERROR",
            issue.message if issue else str(exc),
        )
    if result.report.status == "refused":
        return _Outcome(entry=BatchEntry(source=label, status="refused", conversion=result.report))
    # `result.outputs` is set iff frame_selection=split_all resolved (one file per frame);
    # `result.output` carries the ordinary single-file bytes. Both are per-source outputs.
    bytes_out = (
        list(result.outputs)
        if result.outputs is not None
        else ([result.output] if result.output is not None else [])
    )
    return _Outcome(
        entry=BatchEntry(
            source=label,
            status="converted",
            conversion=result.report,
            validation=result.validation,
        ),
        output_bytes=bytes_out,
        canonical_atom_count=(
            len(result.canonical_out.frames[0].atoms.symbols)
            if result.canonical_out is not None
            else None
        ),
        output_stem=stem,
        canonical=result.canonical_out,
    )


def _failed(source: str, code: str, message: str) -> _Outcome:
    return _Outcome(
        entry=BatchEntry(
            source=source,
            status="failed",
            conversion=None,
            validation=None,
            error=BatchError(code=code, message=message),
        )
    )


def _source_label(path: str, row: int | None) -> str:
    """The reported ``BatchEntry.source`` for a source: its path, or the row-qualified
    ``<path>::row=<i>`` for a fanned-out container row (M55-S3)."""
    return path if row is None else f"{path}{_ROW_LABEL_SEP}{row}"


def _row_stem(path: str, row: int | None) -> str:
    """The output stem for a source: its file stem, or ``<stem>.row<NNNN>`` for a fanned-out
    container row, so N rows of one `.db` write N distinct per-file outputs (M55-S3)."""
    stem = Path(path).stem
    return stem if row is None else f"{stem}.row{row:04d}"


def _write_per_file_outputs(out_dir: Path | None, outcome: _Outcome, target: str) -> bool:
    """Write one converted outcome's outputs into ``out_dir`` (per-file mode), named after the
    outcome's ``output_stem`` (a fanned container row carries its row-qualified stem, M55-S3). A
    ``split_all`` result (multiple frames) lands in a ``<stem>.split/`` subdirectory, mirroring the
    single-file CLI's split-output convention; nothing is written for refused/failed entries.
    Returns whether anything was written."""
    if out_dir is None or outcome.entry.status != "converted" or not outcome.output_bytes:
        return False
    if len(outcome.output_bytes) == 1:
        (out_dir / _output_name_for(outcome.output_stem, target)).write_bytes(
            outcome.output_bytes[0]
        )
        return True
    # frame_selection=split_all: one file per frame, in a <stem>.split/ subdirectory — the
    # single-file CLI's split-output convention, mirrored so a batch names frames alike.
    split_dir = out_dir / f"{outcome.output_stem}.split"
    split_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if target in _NO_SUFFIX_TARGETS else f".{target}"
    for i, chunk in enumerate(outcome.output_bytes):
        (split_dir / f"frame_{i:04d}{suffix}").write_bytes(chunk)
    return True


def _assembled_note(
    registry: Registry, target: str, assembled: bytes, atom_counts: dict[str, int]
) -> str | None:
    """The dataset-level variable-N statement for an assembled artifact. When the assembled sources
    differ in atom count, a **single-object** target — extXYZ — cannot re-parse the whole file as
    one Canonical Object: its single-object re-parse refuses via the **existing**
    ``EXTXYZ_VARIABLE_ATOM_COUNT``, and the note names that property of the assembled file (never a
    per-file loss; the case joins the v2.0 variable-N evidence stream, counted not anecdotal:
    ``tests/conversion/batch/evidence/`` pins the refusal). A **multi-structure container** target
    — ASE ``.db`` — holds variable-N rows natively (its re-parse refuses ``ASEDB_MULTIPLE_ROWS``,
    the ordinary dataset shape, not this variable-N condition), so it warrants no such note."""
    if not assembled:
        return None
    distinct = sorted({n for n in atom_counts.values() if n is not None})
    if len(distinct) <= 1:
        return None
    parser = registry.get_parser(target)
    try:
        parser.parse(io.BytesIO(assembled), filename=f"assembled.{target}")
        return None  # surprisingly one object: no variable-N statement to make
    except ParseError as exc:
        code = exc.issues[0].code if exc.issues else ""
        if code == "EXTXYZ_VARIABLE_ATOM_COUNT":
            counts = ", ".join(f"{p}: {n}" for p, n in atom_counts.items())
            return (
                f"assembled {target} has variable atom counts across frames ({counts}); the "
                f"single-object re-parse of the whole file refuses EXTXYZ_VARIABLE_ATOM_COUNT "
                f"(Part 2 §3.2) — the file is a valid MLIP training set, not one Canonical "
                f"Object. Per-contribution validations stay green; the case is recorded into "
                f"the v2.0 variable-N evidence stream "
                f"(tests/conversion/batch/evidence/v2-variable-n-assemble)."
            )
    # A multi-structure container (a multi-row `.db`) re-parses to a container refusal, not
    # EXTXYZ_VARIABLE_ATOM_COUNT — the healthy dataset shape, no note. Any other single-object
    # re-parse failure would be an assembly bug; the suite pins it.
    return None


def _fanout_note(entries: list[BatchEntry]) -> str | None:
    """The dataset-level fan-out statement (M55-S3). When any resolved source was a
    multi-structure container (a multi-row ASE `.db`) expanded to per-row conversions, this names
    the expansion — a property of the **input** (aggregation, never a per-file loss): each row is
    an independent structure converted through the ordinary per-row path
    (``asedb_row_selection=index``), never a rows-as-frames Canonical Object (Part 2 §3.2)."""
    containers: dict[str, int] = {}
    for entry in entries:
        if _ROW_LABEL_SEP in entry.source:
            container = entry.source.split(_ROW_LABEL_SEP, 1)[0]
            containers[container] = containers.get(container, 0) + 1
    if not containers:
        return None
    parts = "; ".join(f"{path} → {count} per-row conversions" for path, count in containers.items())
    return (
        f"multi-structure container fan-out ({parts}): each row is an independent structure "
        "converted through the ordinary per-row path (asedb_row_selection=index) — a multi-row "
        "ASE .db is aggregation, never one Canonical Object (Part 2 §3.2)."
    )


def _combine_notes(*notes: str | None) -> str | None:
    """Join the dataset-level notes (fan-out first, then the assembled variable-N statement) into
    the single ``BatchReport.note``, dropping the absent ones. Both are properties of the dataset,
    never restatements of a per-file loss (the second-report-schema failure mode)."""
    present = [note for note in notes if note]
    return " ".join(present) if present else None


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
        note=_combine_notes(_fanout_note(reported), note),
    )


def _output_name(source_path: str, target: str) -> str:
    """The per-file output filename for one source: its stem plus the target's conventional
    extension (POSCAR/CONTCAR take none, mirroring the single-file CLI)."""
    return _output_name_for(Path(source_path).stem, target)


def _output_name_for(stem: str, target: str) -> str:
    """The per-file output filename for a given output stem plus the target's conventional
    extension (POSCAR/CONTCAR take none). Shared by the collision pre-check (source stems) and the
    writer (which may hold a fanned container row's ``<stem>.row<NNNN>``, M55-S3)."""
    suffix = "" if target in _NO_SUFFIX_TARGETS else f".{target}"
    return f"{stem}{suffix}"
