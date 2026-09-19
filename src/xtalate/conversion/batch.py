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
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from xtalate._time import utc_now as _utc_now
from xtalate.capabilities import Registry
from xtalate.conversion.engine import ConversionEngine
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.conversion.report import ConversionReport
from xtalate.schema import CanonicalObject, Frame, TrajectoryMetadata
from xtalate.sdk import AssembleContribution, ParseError
from xtalate.validation.engine import ValidationEngine
from xtalate.validation.report import ValidationReport
from xtalate.validation.tolerance import ToleranceProfile

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
    ``conversion`` is ``None`` only for a parse *failure* (no conversion could start).
    ``system`` names the dataset system this source landed in for a directory-assembled target
    (``output_mode: assemble`` to a directory format — ``deepmd_npy``'s ``system_NNN``, M56-S3 /
    D214); ``None`` in per-file mode and for non-directory assemble targets. Additive (default
    ``None``): the field is absent from older serialized reports and round-trips to ``None``."""

    source: str  # The resolved source path (the concrete file that ran).
    status: Literal["converted", "refused", "failed"]
    conversion: ConversionReport | None = None
    validation: ValidationReport | None = None
    error: BatchError | None = None
    system: str | None = None


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
    never a per-file loss.

    ``whole_object_validation`` (M73-S5) is the re-parse-and-diff of a **single-file assembled
    artifact** (extXYZ, ASE ``.db``) read back as **one variable-N Canonical Object** against the
    stacked contributions — the round-trip that schema 2.0 made possible (before M72 a
    mixed-composition assemble could not re-parse as one object at all, so only per-contribution
    validation existed). ``None`` in per-file mode, for a directory-format assemble target (whose
    whole is not one re-parseable file — each contribution is validated in place), and for an
    assemble that produced no output. It is a *property of the assembled whole*; the per-file
    ``BatchEntry.validation`` records still carry each source's own round-trip verbatim."""

    report_id: str
    created_at: str  # ISO 8601 UTC.
    manifest: BatchManifest  # The *resolved* manifest: concrete file list, settings.
    entries: list[BatchEntry] = Field(default_factory=list)
    tallies: BatchTallies
    note: str | None = None
    whole_object_validation: ValidationReport | None = None


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
            # Per-file mode retains only the report model downstream (BATCH-2): the payload bytes
            # and the canonical object served the write (and the assemble combine, which never
            # runs here) — drop them so per-file peak memory tracks the small report models, not
            # Σ output bytes + Σ structure sizes (D56 at the batch tier).
            outcome.output_bytes = []
            outcome.canonical = None
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
    # A **fan-out marker** (M73-S5): set when the first (``row is None``) parse of a source read a
    # multi-structure container — a multi-row ASE ``.db``, which schema 2.0 now reads through as one
    # variable-N object (M73-S5) rather than refusing. ``_convert_source`` reads these to fan the
    # container out to N ordinary per-row conversions (M55 semantics preserved); the marker outcome
    # is never itself reported. ``source_format_id`` is the parsed format; ``source_frame_count`` is
    # the container's row count. Both ``None`` for an ordinary single-structure source.
    source_format_id: str | None = None
    source_frame_count: int | None = None


def _convert_source(
    engine: ConversionEngine,
    registry: Registry,
    entry: SourceEntry,
    manifest: BatchManifest,
    shared_choices: dict[str, dict[str, Any]],
) -> Iterator[_Outcome]:
    """Yield the outcome(s) for one resolved source, lazily (M55-S3, D207; re-triggered M73-S5).

    An ordinary source (or a single-row `.db`, or a `.db` for which the caller already pinned one
    row via ``asedb_row_selection=index``) is one outcome. A **multi-structure container** — a
    `.db` with more than one row — is detected on the first parse (``_convert_one`` returns a
    fan-out marker rather than converting the whole variable-N object), and the batch surface is
    exactly where its rows convert: it **fans out** to N ordinary per-row conversions, each an
    explicit ``asedb_row_selection=index,row=i`` choice (P4), each its own ``BatchEntry`` with a
    ``<path>::row=<i>`` label.

    Schema 2.0 (M72) lets a multi-row `.db` read through as one variable-N Canonical Object
    (M73-S5), so the single-file ``xtalate convert`` no longer refuses it — but the batch keeps its
    fan-out semantics (a dataset is aggregation, not a new model; each row an independent
    structure), now **re-triggered** by ``source_frame_count > 1`` on the detection parse instead
    of by catching the retired refusal. Lazy so ``fail_fast`` stops mid-container — the consumer
    breaks and the remaining rows are never converted."""
    outcome = _convert_one(engine, registry, entry, manifest, shared_choices)
    if outcome.source_format_id == "ase_db" and (outcome.source_frame_count or 0) > 1:
        for row in range(outcome.source_frame_count or 0):
            yield _convert_one(engine, registry, entry, manifest, shared_choices, row=row)
        return
    yield outcome


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
    the per-file conversion validated, so the report keeps its meaning for every file. **Since M73
    the assembled whole is *also* validated** for a single-file target: schema 2.0 lets a
    mixed-composition extXYZ / ASE ``.db`` re-parse as one variable-N Canonical Object, so the
    assembled bytes are diffed against the stacked contributions and the result rides
    ``BatchReport.whole_object_validation`` (before M72 the whole could not re-parse as one object
    at all, so only per-contribution validation existed). A directory-format whole is not one
    re-parseable file — each contribution is validated in place — so it carries no whole-object
    record."""
    engine = ConversionEngine(registry)
    entries: list[_Outcome] = []
    contributions: list[AssembleContribution] = []
    # The outcomes behind ``contributions``, in the same order — so the source→system mapping
    # ``assemble_dir`` returns (index-aligned with its input) can be threaded back onto the
    # entries' ``system`` field and spelled in the aggregate note (DPMD-3/BATCH-1).
    contributing: list[_Outcome] = []
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
                contributing.append(outcome)
                if outcome.canonical_atom_count is not None:
                    atom_counts[outcome.entry.source] = outcome.canonical_atom_count
            if fail_fast and outcome.entry.status != "converted":
                stopped = True
                break
        if stopped:
            break
    assembled = b""
    output_dir: Mapping[str, bytes] | None = None
    exporter = registry.get_exporter(manifest.target)
    target_caps = exporter.capabilities()
    note: str | None = None
    whole_object_validation: ValidationReport | None = None
    if contributions:
        if target_caps.directory_format:
            output_dir, systems = exporter.assemble_dir(contributions)
            source_systems = {
                outcome.entry.source: system
                for outcome, system in zip(contributing, systems, strict=True)
            }
            note = _assemble_dir_note(
                manifest.target, len(contributions), output_dir, source_systems
            )
            for outcome, system in zip(contributing, systems, strict=True):
                outcome.entry.system = system
        else:
            buf = io.BytesIO()
            exporter.assemble(contributions, buf)
            assembled = buf.getvalue()
            note = _assembled_note(manifest.target, atom_counts)
            whole_object_validation = _validate_assembled_whole(
                registry, manifest, contributions, assembled
            )
    if output is not None and assembled:
        Path(output).write_bytes(assembled)
    if output is not None and output_dir:
        root = Path(output)
        root.mkdir(parents=True, exist_ok=True)
        for relative, content in output_dir.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return _assemble_report(
        manifest, resolved, entries, note=note, whole_object_validation=whole_object_validation
    )


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
        if row is None and parsed.format_id == "ase_db" and len(parsed.canonical.frames) > 1:
            # A multi-row ASE `.db` now reads through as one variable-N object (M73-S5), but the
            # batch fans it out to N ordinary per-row conversions (M55 semantics). Return a fan-out
            # marker the caller reads — never convert the whole object on this detection parse. The
            # marker is a ``failed`` shell (never reported); ``_convert_source`` expands it instead.
            marker = _failed(
                label, "ASEDB_MULTIPLE_ROWS", "multi-row ASE database — fanned out per row"
            )
            marker.source_format_id = parsed.format_id
            marker.source_frame_count = len(parsed.canonical.frames)
            return marker
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


def _assembled_note(target: str, atom_counts: dict[str, int]) -> str | None:
    """The dataset-level variable-N statement for a single-file assembled artifact (M54-S2,
    reworded M73-S5). When the assembled sources differ in atom count, the whole file is a
    **variable-N** trajectory — a property of the assembled file, never a per-file loss.

    Before M72 this was a refusal note: a mixed-composition extXYZ could not re-parse as one
    Canonical Object (``EXTXYZ_VARIABLE_ATOM_COUNT``), so the note explained why the whole was
    unvalidatable. Schema 2.0 lifted the constant-N invariant (M72) and M73-S4 retired that reader
    refusal, so the whole now re-parses as one variable-N object and
    :func:`_validate_assembled_whole` proves the round-trip — the note simply records the variable-N
    property (with the per-source counts), no longer an apology for a whole that could not be
    checked. A constant-N assemble (all counts equal) warrants no such note."""
    distinct = sorted({n for n in atom_counts.values() if n is not None})
    if len(distinct) <= 1:
        return None
    counts = ", ".join(f"{p}: {n}" for p, n in atom_counts.items())
    return (
        f"assembled {target} has variable atom counts across frames ({counts}); schema 2.0 holds "
        f"a variable-N trajectory, so the whole file re-parses as one Canonical Object and the "
        f"whole-object validation confirms the round-trip (Part 2 §3.2) — the file is a valid MLIP "
        f"training set. Per-contribution validations stay green."
    )


@dataclass(frozen=True)
class _WholeObjectReportView:
    """A minimal ``ConversionReportView`` for the whole-object assemble validation (M73-S5).

    An assembled trajectory has no single conversion report — each contribution carries its own,
    validated per source. The Validation Engine's absence / report-consistency checks read a report
    for per-source preserved / removed / supplied claims; here those are already validated in place,
    so this view carries a synthetic ``report_id`` and empty claim lists (the two checks pass
    trivially) while the structural + numeric checks do the real work. Empty tuples satisfy the
    ``Sequence`` members of the structural ``ConversionReportView`` Protocol."""

    report_id: str
    preserved: tuple[Any, ...] = ()
    removed: tuple[Any, ...] = ()
    supplied: tuple[Any, ...] = ()
    assumptions: tuple[Any, ...] = ()


def _stack_contributions(contributions: list[AssembleContribution]) -> CanonicalObject:
    """Stack the per-source write-plan-filtered objects into one variable-N object — the *expected*
    reference for :func:`_validate_assembled_whole` (M73-S5). Frames are concatenated in
    contribution (row) order and re-indexed to their position in the stack; ``trajectory`` is set
    when the stack is multi-frame (a lone frame is a structure, Part 2 §3.2). The stacked object
    carries only the frames — each frame's own geometry / dynamics / electronic content is what the
    variable-N structural + numeric checks compare. Per-source ``custom_global`` / metadata /
    absence claims are validated per contribution (each source's own ``ValidationReport``), so the
    stack reuses the first contribution's provenance and adds no object-level metadata; the
    whole-object pass proves the assembled trajectory's structural + numeric round-trip, not a
    second copy of each source's metadata claims."""
    frames: list[Frame] = []
    for contribution in contributions:
        for frame in contribution.canonical.frames:
            frames.append(frame.model_copy(update={"index": len(frames)}))
    trajectory = TrajectoryMetadata(timestep=None) if len(frames) > 1 else None
    return CanonicalObject(
        frames=frames,
        trajectory=trajectory,
        provenance=contributions[0].canonical.provenance,
    )


def _validate_assembled_whole(
    registry: Registry,
    manifest: BatchManifest,
    contributions: list[AssembleContribution],
    assembled: bytes,
) -> ValidationReport | None:
    """Re-parse the single-file assembled artifact as **one variable-N Canonical Object** and diff
    it against the stacked contributions (M73-S5). Returns ``None`` when nothing was assembled.

    This is the round-trip schema 2.0 made possible: before M72 a mixed-composition assembled file
    could not re-parse as one object (the exporter concatenated frames of differing N, and the
    single-object reader refused), so the whole was unvalidatable and only per-contribution
    validation existed. Now the whole re-parses through, so the assembled bytes are validated as a
    trajectory. The Validation Engine's absence / report-consistency checks read a Conversion
    Report; the whole has no single conversion report (each contribution has its own, validated per
    source), so a minimal empty view is passed — those two checks concern per-source preserved /
    removed / supplied claims, already validated in place, and pass trivially here while the
    structural + numeric checks do the real work."""
    if not assembled:
        return None
    expected = _stack_contributions(contributions)
    engine = ValidationEngine(registry)
    view = _WholeObjectReportView(report_id=str(uuid.uuid4()))
    return engine.validate(
        expected=expected,
        output=assembled,
        target_format_id=manifest.target,
        conversion_report=view,
        tolerance=ToleranceProfile.named(manifest.tolerance_profile),
    )


def _assemble_dir_note(
    target: str,
    n_sources: int,
    output_dir: Mapping[str, bytes],
    source_systems: Mapping[str, str],
) -> str | None:
    """The dataset-level grouping statement for a directory-assembled target (M56-S3, D214).

    A directory-format target assembles N converted sources into K dataset systems; the grouping
    itself — for ``deepmd_npy``, by composition, because a DeePMD system is fixed-composition — is
    a **declared property of the target layout** (the batch layer holds no per-format knowledge,
    P2), so this note records the count, the system names, **and which source landed in which
    system** (the ``source_systems`` mapping the target's ``assemble_dir`` returned, keyed by the
    sources the batch layer named) — the wrapper gate: a count and a mapping, never a digest.
    """
    if not output_dir:
        return None
    systems = sorted({path.split("/", 1)[0] for path in output_dir})
    noun = "system" if len(systems) == 1 else "systems"
    assignment = "; ".join(
        f"{source} → {system}" for source, system in sorted(source_systems.items())
    )
    return (
        f"assembled {n_sources} sources into {len(systems)} {target} {noun} "
        f"({', '.join(systems)}) — each source landed in the system named after it "
        f"({assignment}) — a directory-format target is fixed-composition, so sources group by "
        "composition into one system per group, a declared property of the target layout, never "
        "a per-file loss."
    )


def _fanout_note(entries: list[BatchEntry]) -> str | None:
    """The dataset-level fan-out statement (M55-S3; reworded M73-S5). When any resolved source was
    a multi-structure container (a multi-row ASE `.db`) expanded to per-row conversions, this names
    the expansion — a property of the **input**, never a per-file loss: each row is an independent
    structure converted through the ordinary per-row path (``asedb_row_selection=index``). A
    multi-row `.db` *can* read through as one variable-N Canonical Object since M73-S5 (that is what
    a lone ``xtalate convert`` now does), but the batch surface **chooses** per-row aggregation —
    one converted file per structure — as its dataset shape (M55 semantics)."""
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
        "converted through the ordinary per-row path (asedb_row_selection=index) — the batch "
        "surface aggregates a multi-row ASE .db into one converted file per structure (M55)."
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
    whole_object_validation: ValidationReport | None = None,
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
        whole_object_validation=whole_object_validation,
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
