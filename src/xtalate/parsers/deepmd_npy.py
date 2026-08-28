"""DeePMD-kit ``.npy`` system-directory parser (v1.5 M56-S1).

A directory is represented at the SDK boundary as an ordered mapping of relative POSIX paths to
bytes. One DeePMD system becomes one CanonicalObject; set partitions are concatenated in lexical
order and reported rather than interpreted as train/test curation.
"""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from typing import Any

import numpy as np

from xtalate import __version__
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    CanonicalObject,
    Cell,
    Dynamics,
    Electronic,
    Frame,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.schema.elements import is_valid_symbol
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)
from xtalate.sdk.deepmd import (
    BOX_FILE,
    COORD_FILE,
    ENERGY_FILE,
    FORCE_FILE,
    FORMAT_ID,
    TYPE_FILE,
    TYPE_MAP_FILE,
    VIRIAL_FILE,
    set_names,
    stress_from_virial,
)

_PARSER_VERSION = f"{FORMAT_ID}-parser {__version__}"

_EMPTY = "DEEPMD_EMPTY"
_MALFORMED = "DEEPMD_MALFORMED_LAYOUT"
_SHAPES = "DEEPMD_INCONSISTENT_SHAPES"
_MISSING_TYPE_MAP = "DEEPMD_MISSING_TYPE_MAP"
_SET_DROPPED = "DEEPMD_SET_PARTITION_DROPPED"
_SPECIES_HINT = "supply_species"


def _error(code: str, message: str, *, hint: str | None = None) -> ParseError:
    return ParseError(
        [ParseIssue(severity="error", code=code, message=message, recovery_hint=hint)]
    )


def _load(files: Mapping[str, bytes], path: str) -> np.ndarray:
    """Load one known NumPy file without ever enabling pickle deserialization."""
    try:
        value = np.load(BytesIO(files[path]), allow_pickle=False)
    except (KeyError, OSError, ValueError, TypeError, EOFError) as exc:
        raise _error(_MALFORMED, f"could not read DeePMD NumPy file {path!r}: {exc}") from exc
    if not isinstance(value, np.ndarray) or value.dtype.hasobject:
        raise _error(_MALFORMED, f"DeePMD file {path!r} contains an object/pickled array")
    return np.asarray(value)


def _text(files: Mapping[str, bytes], path: str) -> list[str]:
    try:
        return files[path].decode("utf-8").split()
    except KeyError as exc:
        raise _error(_MALFORMED, f"required DeePMD file {path!r} is missing") from exc
    except UnicodeDecodeError as exc:
        raise _error(_MALFORMED, f"DeePMD text file {path!r} is not valid UTF-8") from exc


def _join_sets(files: Mapping[str, bytes], names: list[str], filename: str) -> np.ndarray:
    """Concatenate one file across every set partition, refusing shape-incompatible sets.

    Each set partition must share the same frame count and atom count; a per-set mismatch
    (e.g. ``set.000`` with 3 atoms and ``set.001`` with 4) would otherwise surface as a raw
    ``ValueError`` from ``np.concatenate`` before ``_validate_array`` ever runs — an unhandled
    crash rather than the ``DEEPMD_INCONSISTENT_SHAPES`` refusal this module documents.
    """
    parts = []
    for name in names:
        path = f"{name}/{filename}"
        if path in files:
            parts.append(_load(files, path))
    if not parts:
        raise _error(_MALFORMED, f"each DeePMD system needs {filename!r} in a set directory")
    try:
        return np.concatenate(parts, axis=0)
    except ValueError as exc:
        shapes = ", ".join(
            f"{name}: {part.shape}" for name, part in zip(names, parts, strict=False)
        )
        raise _error(
            _SHAPES,
            f"DeePMD {filename!r} set partitions are shape-incompatible ({shapes}); every "
            "set must share the same frame count and atom count",
        ) from exc


def _validate_array(name: str, value: np.ndarray, frames: int, shape_tail: tuple[int, ...]) -> None:
    if value.ndim != 2 or value.shape[0] != frames or value.shape[1:] != shape_tail:
        raise _error(
            _SHAPES,
            f"DeePMD {name} has shape {value.shape}; expected ({frames}, {shape_tail[0]})",
        )


def _types(
    files: Mapping[str, bytes], n_atoms: int
) -> tuple[list[str] | None, np.ndarray, list[str]]:
    """Return (per-atom symbols, raw type indices, the original type_map.raw tokens).

    The original ``type_map.raw`` token order is returned too so the canonical object can carry
    the source's *numbering* (``type_map`` tokens + ``type.raw`` indices) verbatim — the only way
    the exporter (S2) can write a source-parsed system's numbering back byte-faithfully instead
    of re-deriving a first-appearance map (P1: the numbering the source chose is information).
    """
    try:
        raw = np.asarray([int(token) for token in _text(files, TYPE_FILE)], dtype=np.int64)
    except ValueError as exc:
        raise _error(_MALFORMED, "DeePMD type.raw must contain integer atom type indices") from exc
    if raw.shape != (n_atoms,) or np.any(raw < 0):
        raise _error(_SHAPES, f"DeePMD type.raw has shape {raw.shape}; expected ({n_atoms},)")
    if TYPE_MAP_FILE not in files:
        raise _error(
            _MISSING_TYPE_MAP,
            "DeePMD type_map.raw is missing; numeric atom types need element symbols",
            hint=_SPECIES_HINT,
        )
    type_map = _text(files, TYPE_MAP_FILE)
    if not type_map or any(not is_valid_symbol(symbol) for symbol in type_map):
        raise _error(_MALFORMED, "DeePMD type_map.raw contains an invalid or empty element symbol")
    if int(raw.max(initial=0)) >= len(type_map):
        raise _error(_SHAPES, "DeePMD type.raw refers to a type absent from type_map.raw")
    return [type_map[int(index)] for index in raw], raw, type_map


class DeepmdNpyParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "DeePMD-kit NumPy system"
    version = "0.1.0"
    file_extensions: tuple[str, ...] = ()

    def sniff(self, head: bytes, filename: str | None) -> float:
        return 0.0

    def sniff_dir(self, entries: list[str], dirname: str | None) -> float:
        names = set(entries)
        has_type = TYPE_FILE in names
        has_coord = any(
            entry.startswith("set.") and entry.endswith(f"/{COORD_FILE}") for entry in entries
        )
        has_box = any(
            entry.startswith("set.") and entry.endswith(f"/{BOX_FILE}") for entry in entries
        )
        if has_type and has_coord and has_box:
            return 1.0
        if has_type or has_coord or has_box:
            return 0.35
        return 0.0

    def parse(self, stream: Any, *, filename: str | None) -> ParseResult:
        raise _error(
            _MALFORMED,
            "deepmd_npy is a directory format; pass a directory through parse_dir()",
        )

    def parse_dir(self, files: Mapping[str, bytes], *, dirname: str | None) -> ParseResult:
        names = set_names(files)
        if TYPE_FILE not in files or not names:
            raise _error(
                _MALFORMED,
                "DeePMD system requires type.raw and at least one set.* directory",
            )

        coords = _join_sets(files, names, COORD_FILE).astype(np.float64, copy=False)
        boxes = _join_sets(files, names, BOX_FILE).astype(np.float64, copy=False)
        if coords.shape[0] == 0:
            raise _error(_EMPTY, "DeePMD system contains zero frames")
        if coords.ndim != 2 or coords.shape[1] % 3 != 0:
            raise _error(_SHAPES, f"DeePMD coord.npy has invalid shape {coords.shape}")
        frames, flat_atoms = coords.shape
        n_atoms = flat_atoms // 3
        _validate_array("box.npy", boxes, frames, (9,))
        symbols, type_indices, type_map_tokens = _types(files, n_atoms)
        assert symbols is not None

        force = None
        if any(f"{name}/{FORCE_FILE}" in files for name in names):
            force = _join_sets(files, names, FORCE_FILE).astype(np.float64, copy=False)
            _validate_array("force.npy", force, frames, (n_atoms * 3,))
        energy = None
        if any(f"{name}/{ENERGY_FILE}" in files for name in names):
            energy = _join_sets(files, names, ENERGY_FILE).astype(np.float64, copy=False)
            if energy.ndim == 2 and energy.shape[1] == 1:
                energy = energy[:, 0]
            if energy.ndim != 1 or energy.shape[0] != frames:
                raise _error(
                    _SHAPES,
                    f"DeePMD energy.npy has shape {energy.shape}; expected ({frames},)",
                )
        virial = None
        if any(f"{name}/{VIRIAL_FILE}" in files for name in names):
            virial = _join_sets(files, names, VIRIAL_FILE).astype(np.float64, copy=False)
            _validate_array("virial.npy", virial, frames, (9,))

        issues: list[ParseIssue] = []
        if len(names) > 1:
            issues.append(
                ParseIssue(
                    severity="warning",
                    code=_SET_DROPPED,
                    message=(
                        f"DeePMD set partitions {names} were concatenated in sorted order; the "
                        "source train/test partition was not preserved"
                    ),
                )
            )

        cells = boxes.reshape((-1, 3, 3))
        cell_present = np.any(np.abs(cells) > 0, axis=(1, 2))
        if np.any(cell_present & (np.abs(np.linalg.det(cells)) <= 0)):
            raise _error(_SHAPES, "DeePMD box.npy contains a singular non-zero cell")
        stresses = stress_from_virial(virial, boxes) if virial is not None else None
        object_frames: list[Frame] = []
        for index in range(frames):
            cell = None
            if cell_present[index]:
                cell = Cell(lattice_vectors=cells[index], pbc=(True, True, True))
            object_frames.append(
                Frame(
                    index=index,
                    atoms=AtomsBlock(
                        symbols=symbols, positions=coords[index].reshape((n_atoms, 3))
                    ),
                    cell=cell,
                    dynamics=Dynamics(
                        forces=(force[index].reshape((n_atoms, 3)) if force is not None else None)
                    ),
                    electronic=Electronic(
                        total_energy=(float(energy[index]) if energy is not None else None),
                        stress=(stresses[index] if stresses is not None else None),
                    ),
                )
            )
        custom_global = {
            "deepmd_npy:type_map": type_map_tokens,
            "deepmd_npy:type_indices": type_indices.tolist(),
        }
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=dirname,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom", "energy": "eV", "force": "eV/angstrom"},
            parse_notes=[
                "DeePMD fixed-composition system read from a materialized NumPy directory layout.",
                "virial.npy mapped deterministically to canonical tension-positive stress via "
                "stress × volume.",
            ],
            parser_version=_PARSER_VERSION,
        )
        return ParseResult(
            canonical=CanonicalObject(
                schema_version=SCHEMA_VERSION,
                frames=object_frames,
                trajectory=(TrajectoryMetadata(timestep=None) if frames > 1 else None),
                provenance=provenance,
                user_metadata=UserMetadata(custom_global=custom_global),
            ),
            issues=issues,
        )

    def parse_recover(
        self,
        stream: Any,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
        recovery_context: Mapping[str, object] | None = None,
    ) -> ParseResult:
        """Apply the existing ``missing_species`` choice to a directory payload.

        Directory callers pass the original ordered file mapping in
        ``parameters['directory_files']``; this keeps the recovery scenario and choice vocabulary
        identical to other numeric-type parsers while retaining the directory-native I/O seam.
        """
        if hint != _SPECIES_HINT or choice != "species_map":
            raise _error(
                _MISSING_TYPE_MAP,
                f"deepmd_npy recovery does not support choice {choice!r}",
                hint=_SPECIES_HINT,
            )
        context_spec = (recovery_context or {}).get("missing_species")
        context_parameters = (
            context_spec.get("parameters") if isinstance(context_spec, Mapping) else None
        )
        context_files = (
            context_parameters.get("__xtalate_directory_files")
            if isinstance(context_parameters, Mapping)
            else None
        )
        files = parameters.get("directory_files") or context_files
        if not isinstance(files, Mapping):
            raise _error(
                _MISSING_TYPE_MAP,
                "deepmd_npy species_map recovery requires the original directory file mapping",
                hint=_SPECIES_HINT,
            )
        species = parameters.get("species")
        if isinstance(species, str):
            symbols = species.replace(",", " ").split()
        elif isinstance(species, (list, tuple)):
            symbols = [str(value) for value in species]
        else:
            raise _error(
                _MISSING_TYPE_MAP,
                "species_map needs a 'species' parameter containing ordered symbols",
                hint=_SPECIES_HINT,
            )
        recovered = dict(files)
        recovered[TYPE_MAP_FILE] = (" ".join(symbols)).encode("utf-8")
        return self.parse_dir(recovered, dirname=filename)

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "type_map.raw supplies symbols; missing maps use missing_species recovery."
                    ),
                ),
                "atoms.positions": full,
                "cell.lattice_vectors": FieldCapability(level=CapabilityLevel.PARTIAL),
                "cell.pbc": FieldCapability(level=CapabilityLevel.PARTIAL),
                "dynamics.forces": FieldCapability(level=CapabilityLevel.PARTIAL),
                "electronic.total_energy": FieldCapability(level=CapabilityLevel.PARTIAL),
                "electronic.stress": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Derived deterministically from DeePMD virial.npy and box.npy.",
                ),
                "user_metadata.custom_global": full,
            },
            max_frames=None,
            required_fields=[],
            directory_format=True,
            native_coordinate_system="cartesian",
        )


def make_deepmd_npy_parser() -> DeepmdNpyParser:
    return DeepmdNpyParser()
