"""ASE trajectory (``.traj``) parser (MASTER_SPEC Part 3 §3; v0.3 M14).

The richest format in Phase 1, and the one whose worked example anchors the spec (Part 4 §5).
ASE-backed (DECISIONS.md D7): ``.traj`` is ASE's own binary (ULM) container, so a hand-rolled
reader would re-implement a private serialization format — exactly where wrapping the reference
library earns its keep, as with extXYZ.

Like every ASE wrap, the load-bearing work is **laundering the library's manufactured defaults
back into absence** (P3). ASE always hands back a fully-populated ``Atoms`` — a zero cell, a
``pbc`` value, zeroed-or-derived arrays — for information the source never stated. This module
turns those back into ``None`` so the absence convention is honoured, identically to
``parsers.extxyz``. The laundering rules (each with a golden test in
``tests/parsers/test_ase_traj.py``):

* **Cell.** An all-zero 3×3 (no cell was written) → ``cell = None``. A real cell keeps ASE's
  ``pbc``; an undeclared ``pbc`` cannot occur in ``.traj`` (ASE always persists it) so, unlike
  extXYZ, there is no undeclared-pbc note.
* **Masses.** Present only when the source wrote a ``masses`` array (ASE can *derive* masses from
  atomic numbers, but a derived value is not source data).
* **Momenta / velocities.** Velocities are populated only when the source carried a ``momenta``
  array, unit-converted from ASE's internal velocity unit to canonical Å/fs.
* **Charges / magnetic moments.** ASE persists per-atom ``initial_charges`` / ``initial_magmoms``
  arrays only when set; they map to ``electronic.charges`` / ``electronic.magnetic_moments``.

Field mapping is unit- and sign-safe by construction (D18): positions/lattice (Å), masses (u),
``energy`` (eV), ``forces`` (eV/Å), ``momenta``→velocities (Å/fs). ``stress`` is **not** mapped to
``electronic.stress`` — ASE's stress sign convention cannot be reconciled with the canonical
tension-positive convention without a source-declared convention the file does not carry (D18) —
so it is carried verbatim to ``custom_per_frame['ase_traj:stress']`` exactly as extXYZ does. ASE
``FixAtoms`` constraints map to ``Constraint(kind="fixed_atoms")`` (DECISIONS.md D58); any other
ASE constraint class is carried verbatim to ``custom_per_frame`` with a warning rather than
modelled (the M14 cut line).

The ASE version is recorded in ``provenance.history[].parser_version`` (M14 deliverable 3;
DECISIONS.md D59), so a pin bump that changes parse behaviour is visible in every report.

**Streaming-first.** ``parse`` is defined as ``materialize(parse_stream(...))`` (as XDATCAR), so
the whole-file and streamed readings are one code path that cannot diverge (D56). ASE's
``TrajectoryReader`` is random-access, so ``parse_stream`` genuinely yields one frame at a time
and peak memory tracks the resident frame, not the frame count (M14 deliverable; proven in
``tests/streaming/``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, BinaryIO

import ase
import numpy as np
from ase import units as ase_units
from ase.io.trajectory import TrajectoryReader
from pydantic import JsonValue

from xtalate import __version__
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Cell,
    Constraint,
    Dynamics,
    Electronic,
    Frame,
    TrajectoryMetadata,
)
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    FrameStream,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
    StreamFrame,
    StreamHeader,
    materialize,
)

if TYPE_CHECKING:
    from ase import Atoms

FORMAT_ID = "ase_traj"
_KEY_PREFIX = "ase_traj:"
_STRESS_KEY = "ase_traj:stress"
# Per-atom arrays with a dedicated canonical home; everything else in atoms.arrays is a custom
# per-atom column (Part 2 §3.10). ASE stores charges/magmoms it was *given* as the per-atom
# initial_charges/initial_magmoms arrays.
_RESERVED_ARRAYS = frozenset(
    {"numbers", "positions", "masses", "momenta", "initial_charges", "initial_magmoms"}
)
# Calculator results with a unit- and sign-safe canonical home. Everything else ASE places on the
# calculator (stress, dipole, free_energy, …) is carried verbatim to custom_per_frame (P1, D18).
_MAPPED_CALC_KEYS = frozenset({"energy", "forces", "charges", "magmoms"})
# ASE's velocity unit is Å / (ASE time unit); ase.units.fs is "1 fs in ASE time", so multiplying an
# ASE-unit velocity by it yields Å/fs (mirrors extXYZ; the exporter divides by the same factor).
_VEL_ASE_TO_ANG_PER_FS = ase_units.fs
# ULM magic ASE writes at the head of every .traj file (see ase.io.ulm); the trailing tag names it
# an ASE trajectory specifically. Used only for sniffing — cheap, never authoritative.
_ULM_MAGIC = b"- of Ulm"
_TRAJ_TAG = b"ASE-Trajectory"

#: parser_version string folding in the wrapped ASE version (M14 deliverable 3; D59).
_PARSER_VERSION = f"{FORMAT_ID}-parser {__version__} (ase {ase.__version__})"


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


class AseTrajParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "ASE Trajectory"
    version = "0.1.0"
    file_extensions = (".traj",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # .traj is ASE's binary ULM container: a fixed magic identifies it unambiguously. The
        # extension is a weaker hint (a stray .traj name over non-ULM bytes must not win).
        if head.startswith(_ULM_MAGIC) and _TRAJ_TAG in head[:64]:
            return 1.0
        if filename is not None and filename.endswith(".traj"):
            return 0.3
        return 0.0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56) — so a
        streamed and a whole-file ASE-traj reading are the same code and cannot disagree."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        """Header-eager, frame-lazy ASE-traj parse (M12/M14; Part 3 §2).

        ASE's ``TrajectoryReader`` gives random access to a ``.traj`` without materializing the
        whole trajectory, so the first image is read to establish the object-level header
        (provenance, frame-invariant ``custom_per_atom``) and every image is yielded lazily by
        index — peak memory tracks one frame, not the frame count.

        The constant-atom-count invariant (Part 2 §3.2) and the object-level ``custom_per_atom``
        set are established from frame 0 and re-checked as later frames arrive, mirroring the
        extXYZ streaming parser. A per-atom column or ASE constraint that first appears (or varies)
        in a later frame is a documented streaming nuance (D56): the header is derived from frame 0.
        """
        issues: list[ParseIssue] = []
        try:
            reader = TrajectoryReader(stream)
        except Exception as exc:  # ASE raises many exception types; normalise to the contract
            raise _error(
                "ASE_TRAJ_PARSE_ERROR", f"could not open the file as an ASE trajectory: {exc}"
            ) from exc
        n_images = len(reader)
        if n_images == 0:
            raise _error("ASE_TRAJ_EMPTY", "file contains no frames")

        first = _read_image(reader, 0)
        n_atoms = len(first)
        custom_per_atom = _collect_custom_columns(first)
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=[
                f"read via ASE {ase.__version__} TrajectoryReader; ASE-manufactured defaults "
                "(zero cell, derived masses, zeroed momenta) laundered to absence (P3)."
            ],
            parser_version=_PARSER_VERSION,
        )
        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            trajectory=TrajectoryMetadata(timestep=None),
            custom_per_atom=custom_per_atom,
        )

        def _frames() -> Iterator[StreamFrame]:
            warned_columns: set[str] = set()
            yield self._stream_frame(first, 0, n_atoms, issues)
            for index in range(1, n_images):
                atoms = _read_image(reader, index)
                if len(atoms) != n_atoms:
                    raise _error(
                        "ASE_TRAJ_VARIABLE_ATOM_COUNT",
                        f"frame {index} has {len(atoms)} atoms but frame 0 has {n_atoms}; the "
                        "canonical model requires a constant atom count across frames "
                        "(Part 2 §3.2)",
                        location=f"frame {index}",
                    )
                _check_columns_consistent(atoms, custom_per_atom, warned_columns, issues)
                yield self._stream_frame(atoms, index, n_atoms, issues)

        return FrameStream(header, _frames(), issues=issues)

    def _stream_frame(
        self, atoms: Atoms, index: int, n_atoms: int, issues: list[ParseIssue]
    ) -> StreamFrame:
        """Build one ``StreamFrame`` from one ASE image, reusing the per-field mappers so streamed
        and materialized frames are identical."""
        mapped, carried = _partition_calc(atoms, n_atoms, index, issues)
        charges, magmoms = self._electronic_arrays(atoms, mapped, index, issues, carried)
        per_frame_custom: dict[str, Any] = {}
        for key, value in atoms.info.items():
            per_frame_custom[_namespace(key)] = _as_json(value)
        for key, value in carried.items():
            per_frame_custom[_namespace(key)] = value
        frame = Frame(
            index=index,
            atoms=self._build_atoms(atoms),
            cell=self._build_cell(atoms),
            dynamics=self._build_dynamics(atoms, mapped, index, issues),
            electronic=Electronic(
                total_energy=mapped.get("energy"),
                charges=charges,
                magnetic_moments=magmoms,
            ),
        )
        return StreamFrame(frame=frame, per_frame_custom=per_frame_custom)

    # -- per-frame builders ------------------------------------------------------------

    @staticmethod
    def _build_atoms(atoms: Atoms) -> AtomsBlock:
        positions = np.asarray(atoms.get_positions(), dtype=np.float64)
        # Laundering: ASE can always derive masses from atomic numbers, so only a source-written
        # masses array is honoured; a derived default is absence, not data.
        masses = (
            np.asarray(atoms.arrays["masses"], dtype=np.float64)
            if "masses" in atoms.arrays
            else None
        )
        return AtomsBlock(
            symbols=list(atoms.get_chemical_symbols()),
            positions=positions,
            masses=masses,
        )

    @staticmethod
    def _build_cell(atoms: Atoms) -> Cell | None:
        """Launder ASE's zero-cell default: an all-zero 3×3 means no cell was written → ``None``."""
        lattice = np.asarray(atoms.cell.array, dtype=float)
        if not lattice.any():
            return None
        pbc = (bool(atoms.pbc[0]), bool(atoms.pbc[1]), bool(atoms.pbc[2]))
        return Cell(lattice_vectors=lattice, pbc=pbc)

    def _build_dynamics(
        self, atoms: Atoms, mapped: dict[str, Any], index: int, issues: list[ParseIssue]
    ) -> Dynamics:
        velocities = None
        if atoms.has("momenta"):
            # Laundering: ASE synthesises zero momenta for a file that declared none, so only a
            # real momenta array produces velocities (unit-converted ASE → Å/fs).
            raw = np.asarray(atoms.get_velocities(), dtype=np.float64)
            velocities = raw * _VEL_ASE_TO_ANG_PER_FS
        return Dynamics(
            velocities=velocities,
            forces=mapped.get("forces"),
            constraints=self._build_constraints(atoms, index, issues),
        )

    @staticmethod
    def _build_constraints(
        atoms: Atoms, index: int, issues: list[ParseIssue]
    ) -> list[Constraint] | None:
        """Map ASE ``FixAtoms`` to ``Constraint(kind="fixed_atoms")`` (D58).

        ASE *always* exposes ``atoms.constraints`` as a (possibly empty) list — an empty list is a
        manufactured default, not the source stating "explicitly no constraints" (the ULM container
        carries no such distinction, unlike POSCAR's explicit "Selective dynamics" header). So an
        empty result launders to ``None`` (absence, P3), exactly like the zero cell and zeroed
        momenta; only a non-empty modelled list is returned. Any non-``FixAtoms`` class is carried
        verbatim to ``custom_per_frame`` with a warning rather than modelled (M14 cut line), and
        does not by itself make ``dynamics.constraints`` present."""
        constraints: list[Constraint] = []
        for con in atoms.constraints:
            if type(con).__name__ == "FixAtoms":
                indices = [int(i) for i in np.asarray(con.index).ravel().tolist()]
                constraints.append(
                    Constraint(kind="fixed_atoms", atom_indices=indices, parameters={})
                )
            else:
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="ASE_TRAJ_CONSTRAINT_NOT_MODELLED",
                        message=(
                            f"ASE constraint {type(con).__name__!r} has no canonical mapping; "
                            "carried verbatim in custom_per_frame['ase_traj:constraints'] "
                            "(only FixAtoms is modelled in v0.3)"
                        ),
                        location=f"frame {index}",
                    )
                )
        return constraints or None

    @staticmethod
    def _electronic_arrays(
        atoms: Atoms,
        mapped: dict[str, Any],
        index: int,
        issues: list[ParseIssue],
        carried: dict[str, JsonValue],
    ) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Resolve ``electronic.charges`` / ``electronic.magnetic_moments`` from the two places ASE
        can hold them: the calculator result (a computed output) and the per-atom
        ``initial_charges`` / ``initial_magmoms`` arrays (an input the source set). Precedence: the
        source-written *array* wins the canonical slot; if the calculator *also* carried the value,
        it is carried verbatim to ``custom_per_frame`` rather than silently dropped or overwriting
        (P1). This keeps the mapping deterministic when both are present."""

        def _resolve(array_key: str, calc_key: str, canonical: str) -> np.ndarray | None:
            array_val = (
                np.asarray(atoms.arrays[array_key], dtype=np.float64)
                if array_key in atoms.arrays
                else None
            )
            # _partition_calc stores charges/magmoms as float64 ndarrays; typed here so the
            # function's ndarray|None return does not leak Any from the dict.pop.
            calc_val: np.ndarray | None = mapped.pop(canonical, None)
            if array_val is not None:
                if calc_val is not None:
                    carried[calc_key] = _as_json(calc_val)
                    issues.append(
                        ParseIssue(
                            severity="warning",
                            code="ASE_TRAJ_CHARGE_MOMENT_BOTH_PRESENT",
                            message=(
                                f"both a per-atom {array_key!r} array and a calculator "
                                f"{calc_key!r} result are present; the array is mapped to "
                                f"electronic.{canonical} and the calculator value carried in "
                                f"custom_per_frame['{_KEY_PREFIX}{calc_key}']"
                            ),
                            location=f"frame {index}",
                        )
                    )
                return array_val
            return calc_val

        charges = _resolve("initial_charges", "charges", "charges")
        magmoms = _resolve("initial_magmoms", "magmoms", "magnetic_moments")
        return charges, magmoms

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        partial = CapabilityLevel.PARTIAL
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "atoms.masses": FieldCapability(
                    level=partial, notes="Only when a masses array is written (never ASE-derived)."
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=partial, notes="Only when a non-zero cell is written."
                ),
                "cell.pbc": FieldCapability(
                    level=partial, notes="ASE always persists pbc when a cell is present."
                ),
                "dynamics.velocities": FieldCapability(
                    level=partial, notes="Only when a momenta array is present; unit-converted."
                ),
                "dynamics.forces": FieldCapability(
                    level=partial, notes="Only when the calculator carried forces."
                ),
                "dynamics.constraints": FieldCapability(
                    level=partial, notes="ASE FixAtoms → fixed_atoms; other constraints carried."
                ),
                "electronic.total_energy": FieldCapability(
                    level=partial, notes="Only when the calculator carried energy."
                ),
                "electronic.charges": FieldCapability(
                    level=partial, notes="From initial_charges array or calculator charges."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="From initial_magmoms array or calculator magmoms."
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Arbitrary per-atom arrays."
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="atoms.info key-values; carries stress verbatim (D18).",
                ),
            },
            max_frames=None,  # a trajectory: unbounded frame count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            lossy_notes=[
                "stress carried verbatim in user_metadata.custom_per_frame['ase_traj:stress'] "
                "rather than electronic.stress (sign convention).",
            ],
        )


def _namespace(key: str) -> str:
    """Tag a raw ASE info/column key with the ``ase_traj:`` namespace (Part 2 §6.1) unless it
    already carries a ``<format>:`` namespace (a cross-format key kept verbatim), mirroring
    ``parsers.extxyz._namespace``."""
    return key if ":" in key else f"{_KEY_PREFIX}{key}"


def _read_image(reader: TrajectoryReader, index: int) -> Atoms:
    """Read one image, normalising ASE's many exception types to the ParseError contract (§5)."""
    try:
        return reader[index]
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 — ASE raises many types; normalise to the contract
        raise _error(
            "ASE_TRAJ_PARSE_ERROR",
            f"ASE could not read frame {index} of the trajectory: {exc}",
            location=f"frame {index}",
        ) from exc


def _partition_calc(
    atoms: Atoms, n_atoms: int, frame_index: int, issues: list[ParseIssue]
) -> tuple[dict[str, Any], dict[str, JsonValue]]:
    """Split a frame's ASE calculator results into (mapped, carried), mirroring extXYZ.

    ``mapped`` holds results with a unit- and sign-safe canonical home (energy → eV, forces → eV/Å,
    per-atom ``charges`` → e, per-atom ``magmoms`` → μB). ``carried`` holds everything else —
    ``stress`` (sign convention unreconcilable, D18) and any unexpected key — routed verbatim to
    ``custom_per_frame`` so nothing ASE parsed is dropped silently (P1). An unexpected key warns.
    """
    mapped: dict[str, Any] = {}
    carried: dict[str, JsonValue] = {}
    if atoms.calc is None:
        return mapped, carried
    for key, value in atoms.calc.results.items():
        if key == "energy":
            mapped["energy"] = float(value)
        elif key == "forces":
            mapped["forces"] = np.asarray(value, dtype=np.float64)
        elif key in ("charges", "magmoms") and _is_per_atom_scalar(value, n_atoms):
            mapped[key] = np.asarray(value, dtype=np.float64)
        else:
            carried[key] = _as_json(value)
            if key not in _MAPPED_CALC_KEYS and key != "stress":
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="ASE_TRAJ_UNMAPPED_RESULT_CARRIED",
                        message=f"calculator result {key!r} has no canonical field; carried "
                        f"verbatim in user_metadata.custom_per_frame['{_KEY_PREFIX}{key}']",
                        location=f"frame {frame_index}",
                    )
                )
    return mapped, carried


def _collect_custom_columns(atoms: Atoms) -> dict[str, Any]:
    """Arbitrary per-atom arrays → ``custom_per_atom['ase_traj:<name>']`` (first dim N). Numeric
    columns become float64 ndarrays; non-numeric columns become length-N JSON lists — the two arms
    of the ``custom_per_atom`` union (Part 2 §3.10). Established from frame 0 (object-level)."""
    columns: dict[str, Any] = {}
    for name, array in atoms.arrays.items():
        if name in _RESERVED_ARRAYS:
            continue
        values = np.asarray(array)
        if np.issubdtype(values.dtype, np.number):
            columns[_namespace(name)] = values.astype(float, copy=False)
        else:
            columns[_namespace(name)] = [_as_json(v) for v in values]
    return columns


def _check_columns_consistent(
    atoms: Atoms,
    frame0_columns: dict[str, Any],
    warned: set[str],
    issues: list[ParseIssue],
) -> None:
    """Warn once per per-atom column whose values differ from frame 0's: ``custom_per_atom`` is
    stored once per object (Part 2 §3.10), so a column that varies across frames cannot be
    represented losslessly and only frame 0's values are carried (mirrors extXYZ)."""
    for name, array in atoms.arrays.items():
        if name in _RESERVED_ARRAYS:
            continue
        key = _namespace(name)
        if key in warned or key not in frame0_columns:
            continue
        if not np.array_equal(np.asarray(array), np.asarray(frame0_columns[key])):
            warned.add(key)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="ASE_TRAJ_PER_FRAME_COLUMN_NOT_REPRESENTABLE",
                    message=(
                        f"per-atom column {name!r} varies across frames; the canonical model "
                        "stores per-atom custom arrays once per object (Part 2 §3.10), so only the "
                        "first frame's values are carried"
                    ),
                )
            )


def _is_per_atom_scalar(value: Any, n_atoms: int) -> bool:
    """True if ``value`` is a 1-D per-atom array (fits ArrayN)."""
    array = np.asarray(value)
    return array.ndim == 1 and array.shape[0] == n_atoms


def _as_json(value: Any) -> JsonValue:
    """Coerce an ASE info/calc value into a JSON-serialisable scalar or nested list."""
    if isinstance(value, np.ndarray):
        return value.tolist()  # type: ignore[no-any-return]
    if isinstance(value, np.generic):
        return value.item()  # type: ignore[no-any-return]
    return value  # type: ignore[no-any-return]


def make_ase_traj_parser() -> AseTrajParser:
    return AseTrajParser()
