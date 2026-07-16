"""Extended XYZ parser (MASTER_SPEC Part 3 §2, §3, §4.2).

ASE-backed (DECISIONS.md D7): the ``Lattice=`` / ``Properties=`` grammar with typed,
variable per-atom columns is exactly where a battle-tested reader earns its keep, so ASE is
wrapped here rather than re-implemented. The wrap is not free — ASE is an I/O workhorse that
*always* hands back a fully-populated ``Atoms`` object, inventing a zero cell, ``pbc``, and
zeroed momenta for information the source never stated. Turning those library defaults back
into **absence** (``None``) is the single most important thing this module does (Part 3 §2,
"Wrapping ASE/pymatgen"): it is the difference between honoring the absence convention (P3)
and silently fabricating a degenerate cell nobody wrote.

Laundering rules applied here (each has a golden test in ``tests/parsers/test_extxyz.py``):

* **Cell.** ASE returns an all-zero 3×3 when no ``Lattice=`` key is present → ``cell = None``.
* **PBC.** ASE defaults ``pbc`` to ``(True, True, True)`` whenever a lattice exists, even if
  the file declared no ``pbc=`` key. A cell is kept (the lattice is real) with that
  convention value, but the fact that it was *not declared* is recorded in ``parse_notes``
  (the extXYZ analogue of the POSCAR format-defined-PBC note, Part 3 §3 n.3) — never passed
  off as source data.
* **Momenta / velocities.** ASE synthesises zero momenta for a file that declared none;
  velocities are populated **only** when the source carried a ``momenta`` column, and are
  unit-converted from ASE's internal velocity unit to canonical Å/fs.
* **Masses.** ASE can always *compute* masses from atomic numbers; ``atoms.masses`` is set
  only when the file actually declared a ``masses`` column.

Field mapping is unit- and sign-safe by construction (DECISIONS.md D18): positions (Å),
lattice (Å), masses (u), ``energy`` (eV), ``forces`` (eV/Å) and ``momenta``→velocities (Å/fs)
map to their canonical homes; every other ``Properties=`` column carries through verbatim to
``user_metadata.custom_per_atom["extxyz:<name>"]`` and every comment-line key=value to
``custom_per_frame["extxyz:<key>"]`` (Part 2 §6.1, §3.10). ``stress`` is carried the same way
rather than mapped to ``electronic.stress``, because ASE's stress *sign convention* cannot be
reconciled with the canonical tension-positive convention (Part 2 §3.7.1) without a
source-declared convention the file does not carry — see DECISIONS.md D18.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, BinaryIO

import numpy as np
from ase import units as ase_units
from ase.io import read as ase_read
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance, decode_text
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
)

if TYPE_CHECKING:
    from ase import Atoms

FORMAT_ID = "extxyz"
_KEY_PREFIX = "extxyz:"
# ASE stores per-frame results (energy/forces/stress/charges/magmoms/…) on a
# SinglePointCalculator; everything else the source declared lives in atoms.arrays (per-atom
# columns) or atoms.info (comment key-values). These array names have dedicated canonical
# homes and are not treated as custom columns.
_RESERVED_ARRAYS = frozenset({"numbers", "positions", "momenta", "masses"})
# Calculator results with a unit- and sign-safe canonical home. Everything ASE places on the
# calculator that is NOT here (e.g. stress, dipole, free_energy) is carried through verbatim
# to custom_per_frame so nothing is dropped silently (P1) — see _partition_calc.
_MAPPED_CALC_KEYS = frozenset({"energy", "forces", "charges", "magmoms"})
_EXTXYZ_MARKERS = ("Lattice=", "Properties=")
# ASE's velocity unit is Å / (ASE time unit); ase.units.fs is "1 fs expressed in ASE time",
# so multiplying an ASE-unit velocity by it yields Å/fs (verified by round-trip).
_VEL_ASE_TO_ANG_PER_FS = ase_units.fs
_PBC_KEY_RE = re.compile(r"\bpbc\s*=", re.IGNORECASE)


def _namespace(key: str) -> str:
    """Tag a raw extXYZ comment/column key with the ``extxyz:`` format namespace to record its
    provenance (Part 2 §6.1) — **unless it already carries a ``<format>:`` namespace**.

    A bare key (``config_type``) becomes ``extxyz:config_type``. A key that already contains a
    ``:`` — e.g. ``xyz:comment`` written onto an extXYZ comment line by a cross-format export — is
    kept verbatim: double-namespacing it to ``extxyz:xyz:comment`` would both hide its true origin
    and change its canonical path, false-failing the Validation Engine's ``metadata_preservation``
    check on an ``X → Canonical → extXYZ`` round-trip (the value survives, but under a changed key).
    The exporter mirror (``exporters.extxyz``) strips only its own ``extxyz:`` prefix, so an
    ``extxyz:``-origin key round-trips (write ``foo`` → re-read ``extxyz:foo``) while a foreign key
    is written and re-read verbatim."""
    return key if ":" in key else f"{_KEY_PREFIX}{key}"


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


def _frame_comment_lines(lines: list[str]) -> list[str]:
    """Walk the XYZ block structure and return each frame's raw comment line.

    ASE consumes ``Lattice=`` / ``Properties=`` / ``pbc=`` and does not tell us whether a
    key was *declared* vs. defaulted — but the absence convention turns on exactly that
    distinction for ``pbc`` (an undeclared ``pbc`` is a convention value, not source data).
    So the raw comment line is recovered here to detect key presence, cheaply and without a
    second full parse. Structurally malformed input is left for ASE to reject uniformly.
    """
    comments: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == "":
            i += 1
            continue
        try:
            count = int(lines[i].strip())
        except ValueError:
            break  # not a count line; let ASE produce the authoritative error
        if count <= 0 or i + 1 >= n:
            break
        comments.append(lines[i + 1])
        i += 2 + count
    return comments


class ExtxyzParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "Extended XYZ"
    version = "0.1.0"
    file_extensions = (".xyz", ".extxyz")

    def sniff(self, head: bytes, filename: str | None) -> float:
        # extXYZ is a superset of XYZ (Part 3 §3 n.2): its signature is a comment line
        # carrying Lattice= / Properties= key-value markers. Without them a file is plain
        # XYZ and the plain parser should win — so score low, not zero, on a bare .xyz.
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            return 0.0
        try:
            count = int(lines[0].strip())
        except ValueError:
            return 0.0
        if count <= 0 or len(lines) < 2:
            return 0.0
        if any(marker in lines[1] for marker in _EXTXYZ_MARKERS):
            return 0.9  # unambiguous extXYZ header — beats plain XYZ's marker-capped 0.6
        return 0.2  # parses as XYZ but shows no extXYZ markers: yield to the plain parser

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        text = decode_text(stream.read(), format_id=FORMAT_ID)
        if text.strip() == "":
            raise _error("EXTXYZ_EMPTY", "file contains no frames")
        raw_comments = _frame_comment_lines(text.splitlines())
        try:
            images = ase_read(io.StringIO(text), format="extxyz", index=":")
        except Exception as exc:  # ASE raises many exception types; normalise to the contract
            raise _error(
                "EXTXYZ_PARSE_ERROR",
                f"ASE could not read the file as extended XYZ: {exc}",
            ) from exc
        atoms_list: list[Atoms] = list(images)
        if not atoms_list:
            raise _error("EXTXYZ_EMPTY", "file contains no frames")

        n_atoms = len(atoms_list[0])
        for k, atoms in enumerate(atoms_list):
            if len(atoms) != n_atoms:
                # The canonical model fixes N across frames (Part 2 §3.2); a variable-N
                # extXYZ trajectory cannot be represented and must not be silently reshaped.
                raise _error(
                    "EXTXYZ_VARIABLE_ATOM_COUNT",
                    f"frame {k} has {len(atoms)} atoms but frame 0 has {n_atoms}; the canonical "
                    "model requires a constant atom count across frames (Part 2 §3.2)",
                    location=f"frame {k}",
                )

        issues: list[ParseIssue] = []
        parse_notes: list[str] = []
        frames: list[Frame] = []
        carried_calc: list[dict[str, JsonValue]] = []
        undeclared_pbc = False

        for index, atoms in enumerate(atoms_list):
            comment = raw_comments[index] if index < len(raw_comments) else ""
            cell, frame_pbc_note = self._build_cell(atoms, comment)
            undeclared_pbc = undeclared_pbc or frame_pbc_note
            mapped, carried = _partition_calc(atoms, n_atoms, index, issues)
            carried_calc.append(carried)
            frames.append(
                Frame(
                    index=index,
                    atoms=self._build_atoms(atoms),
                    cell=cell,
                    dynamics=self._build_dynamics(atoms, mapped),
                    electronic=Electronic(
                        total_energy=mapped.get("energy"),
                        charges=mapped.get("charges"),
                        magnetic_moments=mapped.get("magmoms"),
                    ),
                )
            )

        if undeclared_pbc:
            parse_notes.append(
                "pbc not declared for a lattice-bearing frame; set to (true,true,true) per the "
                "extXYZ convention that a Lattice implies full periodicity (recorded, not assumed)."
            )
        if any(atoms.has("momenta") for atoms in atoms_list):
            # Note whenever a momenta column was present — including an explicit all-zero one (a
            # source stating the atoms are at rest is information, §2 rule 3), not only when some
            # velocity is nonzero.
            parse_notes.append(
                "velocities converted from ASE internal units to Å/fs (source 'momenta' column)."
            )

        user_metadata = self._build_user_metadata(atoms_list, carried_calc, issues)
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=parse_notes,
        )
        trajectory = None if len(frames) == 1 else TrajectoryMetadata(timestep=None)
        canonical = CanonicalObject(
            frames=frames,
            trajectory=trajectory,
            provenance=provenance,
            user_metadata=user_metadata,
        )
        return ParseResult(canonical=canonical, issues=issues)

    # -- streaming parse (M12) ---------------------------------------------------------

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        """Header-eager, frame-lazy extXYZ parse (M12; MASTER_SPEC Part 3 §2).

        Reads the file **one frame block at a time** off the raw byte stream — never slurping the
        whole trajectory into a string — so peak memory tracks the resident chunk, not the frame
        count. The first block is read eagerly to establish the object-level header (atom count,
        the frame-invariant ``custom_per_atom`` columns, and the ``parse_notes``); every remaining
        block is yielded lazily. Each frame reuses the *same* per-frame builders as ``parse`` (so
        the laundering rules — zero cell → ``None``, undeclared pbc recorded, synthesised momenta
        dropped — apply identically), and the constant-atom-count invariant (Part 2 §3.2) is
        checked as frames arrive, raising ``ParseError`` at the offending frame (Part 3 §5).

        ``parse_notes`` are derived from the first frame's declaration state (pbc-declared, momenta
        present). For the homogeneous trajectories extXYZ overwhelmingly holds — every frame written
        by the same tool with the same columns — this is exact; a trajectory whose *later* frames
        first introduce a lattice or momenta is a documented streaming nuance (DECISIONS.md D56).
        The Conversion Report carries no ``parse_notes``, so this never affects report truth
        (standing rule 3)."""
        issues: list[ParseIssue] = []
        blocks = _iter_extxyz_blocks(stream)
        try:
            first_block, first_comment = next(blocks)
        except StopIteration:
            raise _error("EXTXYZ_EMPTY", "file contains no frames") from None
        first_atoms = _read_block(first_block, 0)
        n_atoms = len(first_atoms)

        first_cell, first_undeclared_pbc = self._build_cell(first_atoms, first_comment)
        parse_notes: list[str] = []
        if first_undeclared_pbc:
            parse_notes.append(
                "pbc not declared for a lattice-bearing frame; set to (true,true,true) per the "
                "extXYZ convention that a Lattice implies full periodicity (recorded, not assumed)."
            )
        if first_atoms.has("momenta"):
            parse_notes.append(
                "velocities converted from ASE internal units to Å/fs (source 'momenta' column)."
            )
        # custom_per_atom is object-level and frame-invariant (Part 2 §3.10): established from the
        # first frame's Properties= columns and re-checked as later frames stream in.
        custom_per_atom = _collect_custom_columns_single(first_atoms)
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=parse_notes,
        )
        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            trajectory=TrajectoryMetadata(timestep=None),
            custom_per_atom=custom_per_atom,
        )

        def _frames() -> Iterator[StreamFrame]:
            warned_columns: set[str] = set()
            yield self._stream_frame(first_atoms, first_comment, first_cell, 0, n_atoms, issues)
            index = 1
            for block, comment in blocks:
                atoms = _read_block(block, index)
                if len(atoms) != n_atoms:
                    raise _error(
                        "EXTXYZ_VARIABLE_ATOM_COUNT",
                        f"frame {index} has {len(atoms)} atoms but frame 0 has {n_atoms}; the "
                        "canonical model requires a constant atom count across frames "
                        "(Part 2 §3.2)",
                        location=f"frame {index}",
                    )
                _check_columns_consistent(atoms, custom_per_atom, warned_columns, issues)
                cell, _ = self._build_cell(atoms, comment)
                yield self._stream_frame(atoms, comment, cell, index, n_atoms, issues)
                index += 1

        return FrameStream(header, _frames(), issues=issues)

    def _stream_frame(
        self,
        atoms: Atoms,
        comment: str,
        cell: Cell | None,
        index: int,
        n_atoms: int,
        issues: list[ParseIssue],
    ) -> StreamFrame:
        """Build one ``StreamFrame`` (Frame + its per-frame custom slice) from one ASE image,
        reusing the whole-file per-frame mappers so streamed and materialized frames match."""
        mapped, carried = _partition_calc(atoms, n_atoms, index, issues)
        per_frame_custom: dict[str, Any] = {}
        for key in atoms.info:
            per_frame_custom[_namespace(key)] = _as_json(atoms.info.get(key))
        for key, value in carried.items():
            per_frame_custom[_namespace(key)] = value
        frame = Frame(
            index=index,
            atoms=self._build_atoms(atoms),
            cell=cell,
            dynamics=self._build_dynamics(atoms, mapped),
            electronic=Electronic(
                total_energy=mapped.get("energy"),
                charges=mapped.get("charges"),
                magnetic_moments=mapped.get("magmoms"),
            ),
        )
        return StreamFrame(frame=frame, per_frame_custom=per_frame_custom)

    # -- per-frame builders ------------------------------------------------------------

    @staticmethod
    def _build_atoms(atoms: Atoms) -> AtomsBlock:
        positions = np.asarray(atoms.get_positions(), dtype=np.float64)
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
    def _build_cell(atoms: Atoms, comment: str) -> tuple[Cell | None, bool]:
        """Return ``(cell, pbc_was_undeclared)`` — laundering the ASE zero-cell default."""
        lattice = np.asarray(atoms.cell.array, dtype=float)
        if not lattice.any():
            return None, False  # no Lattice= key: ASE's zero cell is absence, not a cell
        pbc = (bool(atoms.pbc[0]), bool(atoms.pbc[1]), bool(atoms.pbc[2]))
        undeclared = _PBC_KEY_RE.search(comment) is None
        return Cell(lattice_vectors=lattice, pbc=pbc), undeclared

    @staticmethod
    def _build_dynamics(atoms: Atoms, mapped: dict[str, Any]) -> Dynamics:
        velocities = None
        if atoms.has("momenta"):
            # Laundering: ASE synthesises zero momenta for a file that declared none, so only
            # a real momenta column produces velocities (unit-converted ASE → Å/fs).
            velocities = (
                np.asarray(atoms.get_velocities(), dtype=np.float64) * _VEL_ASE_TO_ANG_PER_FS
            )
        forces = mapped.get("forces")
        return Dynamics(velocities=velocities, forces=forces)

    # -- object-level carry-through ----------------------------------------------------

    def _build_user_metadata(
        self,
        atoms_list: list[Atoms],
        carried_calc: list[dict[str, JsonValue]],
        issues: list[ParseIssue],
    ) -> UserMetadata:
        custom_per_atom = self._collect_custom_columns(atoms_list, issues)
        custom_per_frame = self._collect_comment_metadata(atoms_list, carried_calc)
        return UserMetadata(
            custom_per_atom=custom_per_atom,
            custom_per_frame=custom_per_frame,
        )

    @staticmethod
    def _collect_custom_columns(
        atoms_list: list[Atoms], issues: list[ParseIssue]
    ) -> dict[str, Any]:
        """Arbitrary ``Properties=`` columns → ``custom_per_atom['extxyz:<name>']`` (first dim N).

        ``custom_per_atom`` is object-level (Part 2 §3.10), so a column that *varies* across
        frames of a trajectory cannot be represented losslessly. Rather than silently keep
        one frame's values, that is reported as a warning (P1) and frame 0 is carried.
        """
        first = atoms_list[0]
        columns: dict[str, Any] = {}
        for name, array in first.arrays.items():
            if name in _RESERVED_ARRAYS:
                continue
            values = np.asarray(array)
            consistent = all(
                name in a.arrays and np.array_equal(np.asarray(a.arrays[name]), values)
                for a in atoms_list
            )
            if not consistent:
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE",
                        message=(
                            f"per-atom column {name!r} varies across frames; the canonical model "
                            "stores per-atom custom arrays once per object (Part 2 §3.10), so only "
                            "the first frame's values are carried"
                        ),
                    )
                )
            # Numeric columns are stored as a float64 ndarray (ArrayNx); non-numeric columns (a
            # string ``:S:`` property such as a per-atom label) are carried as a length-N list of
            # JSON scalars — the second arm of the custom_per_atom union (Part 2 §3.10). Forcing a
            # string column through astype(float) previously raised a raw ValueError, escaping the
            # ParseResult/ParseError contract (§5).
            if np.issubdtype(values.dtype, np.number):
                columns[_namespace(name)] = values.astype(float, copy=False)
            else:
                columns[_namespace(name)] = [_as_json(v) for v in values]
        return columns

    @staticmethod
    def _collect_comment_metadata(
        atoms_list: list[Atoms], carried_calc: list[dict[str, JsonValue]]
    ) -> dict[str, Any]:
        """Comment key=value pairs + carried calc results → ``custom_per_frame`` (first dim F).

        Every key seen in any frame becomes a length-F list (``None`` where a frame omits it),
        so the per-frame association the carry-through rule requires (Part 2 §6.1) is kept.
        ``carried_calc[i]`` holds the calculator results for frame ``i`` that have no canonical
        home (stress, and anything unexpected) — carried, never dropped (P1).
        """
        info_keys: list[str] = []
        for atoms in atoms_list:
            for key in atoms.info:
                if key not in info_keys:
                    info_keys.append(key)
        calc_keys: list[str] = []
        for carried in carried_calc:
            for key in carried:
                if key not in calc_keys:
                    calc_keys.append(key)

        per_frame: dict[str, Any] = {}
        for key in info_keys:
            per_frame[_namespace(key)] = [_as_json(atoms.info.get(key)) for atoms in atoms_list]
        for key in calc_keys:
            per_frame[_namespace(key)] = [carried.get(key) for carried in carried_calc]
        return per_frame

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
                    level=partial, notes="Only when declared in Properties= columns."
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=partial, notes="Only when Lattice= key present."
                ),
                "cell.pbc": FieldCapability(
                    level=partial,
                    notes="From pbc= key; (T,T,T) by extXYZ convention when a Lattice has no "
                    "pbc= key (recorded in parse_notes).",
                ),
                "dynamics.velocities": FieldCapability(
                    level=partial, notes="Only when a momenta column is present; unit-converted."
                ),
                "dynamics.forces": FieldCapability(
                    level=partial, notes="Only when a forces column is present."
                ),
                "electronic.total_energy": FieldCapability(
                    level=partial, notes="Only when energy= key present."
                ),
                "electronic.charges": FieldCapability(
                    level=partial, notes="Only when a per-atom charge column is present."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="Only when a per-atom magmoms column is present."
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Arbitrary Properties= columns."
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Arbitrary comment-line key-value pairs; carries stress verbatim (D18).",
                ),
            },
            max_frames=None,
            required_fields=[],
            native_coordinate_system="cartesian",
            # v0.1 carries stress through custom_per_frame rather than mapping electronic.stress,
            # to avoid a silent sign-convention error (DECISIONS.md D18; Part 2 §3.7.1).
            lossy_notes=[
                "stress/virial carried verbatim in user_metadata.custom_per_frame['extxyz:stress'] "
                "rather than electronic.stress (v0.1; DECISIONS.md D18).",
            ],
        )


def _partition_calc(
    atoms: Atoms, n_atoms: int, frame_index: int, issues: list[ParseIssue]
) -> tuple[dict[str, Any], dict[str, JsonValue]]:
    """Split a frame's ASE calculator results into (mapped, carried).

    ``mapped`` holds the results with a unit- and sign-safe canonical home (energy → eV,
    forces → eV/Å, per-atom ``charges`` → e cation-positive, per-atom ``magmoms`` → μB
    spin-up-positive; all matching Part 2 §3.7.1). ``carried`` holds everything else — ``stress``
    (whose sign convention cannot be reconciled without a source-declared convention,
    DECISIONS.md D18) and any unexpected key — routed verbatim to ``custom_per_frame`` so a
    result ASE parsed is never dropped silently (P1). An unexpected carried key warns.
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
            canonical = "charges" if key == "charges" else "magmoms"
            mapped[canonical] = np.asarray(value, dtype=np.float64)
        else:
            carried[key] = _as_json(value)
            if key not in _MAPPED_CALC_KEYS and key != "stress":
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="EXTXYZ_UNMAPPED_RESULT_CARRIED",
                        message=f"calculator result {key!r} has no canonical field; carried "
                        f"verbatim in user_metadata.custom_per_frame['{_KEY_PREFIX}{key}']",
                        location=f"frame {frame_index}",
                    )
                )
    return mapped, carried


def _iter_extxyz_blocks(stream: BinaryIO) -> Iterator[tuple[str, str]]:
    """Yield ``(block_text, comment_line)`` one frame block at a time off the raw byte stream.

    An extXYZ frame is a count line, a comment line, then ``count`` atom lines. Reading the file
    block-by-block (rather than ``read()``-ing it whole) is what keeps the streaming parser's peak
    memory bounded by one frame, not the trajectory. A byte sequence that is not UTF-8, a
    non-integer count line, or a block truncated before its atom lines complete each raise a
    structured ``ParseError`` (Part 3 §5) at the point of failure — mid-stream for later frames."""

    def _readline() -> str | None:
        raw = stream.readline()
        if raw == b"":
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(
                "EXTXYZ_ENCODING_ERROR",
                f"file is not valid UTF-8 text (byte 0x{raw[exc.start]:02x}); extxyz is a text "
                "format",
            ) from exc

    index = 0
    while True:
        line = _readline()
        if line is None:
            return
        if line.strip() == "":
            continue
        try:
            count = int(line.strip())
        except ValueError:
            raise _error(
                "EXTXYZ_PARSE_ERROR",
                f"expected an atom-count line, got {line.strip()!r}",
                location=f"frame {index}",
            ) from None
        if count <= 0:
            raise _error(
                "EXTXYZ_PARSE_ERROR",
                f"atom count must be positive, got {count}",
                location=f"frame {index}",
            )
        comment = _readline()
        if comment is None:
            raise _error(
                "EXTXYZ_PARSE_ERROR",
                "file ended before the comment line of a frame",
                location=f"frame {index}",
            )
        atom_lines: list[str] = []
        for _ in range(count):
            atom_line = _readline()
            if atom_line is None:
                raise _error(
                    "EXTXYZ_PARSE_ERROR",
                    f"frame {index} declares {count} atoms but the file ended after "
                    f"{len(atom_lines)}",
                    location=f"frame {index}",
                )
            atom_lines.append(atom_line.rstrip("\n"))
        block = f"{count}\n{comment.rstrip(chr(10))}\n" + "\n".join(atom_lines) + "\n"
        yield block, comment
        index += 1


def _read_block(block: str, index: int) -> Atoms:
    """Parse one frame block into a single ASE ``Atoms``, normalising ASE's many exception types
    to the ``ParseError`` contract (§5) with the offending frame located."""
    try:
        return ase_read(io.StringIO(block), format="extxyz", index=0)
    except Exception as exc:  # ASE raises many exception types; normalise to the contract
        raise _error(
            "EXTXYZ_PARSE_ERROR",
            f"ASE could not read frame {index} as extended XYZ: {exc}",
            location=f"frame {index}",
        ) from exc


def _collect_custom_columns_single(atoms: Atoms) -> dict[str, Any]:
    """The ``custom_per_atom`` columns of a *single* frame — the streaming analogue of
    ``_collect_custom_columns`` restricted to one image (frame 0 establishes the object-level set,
    Part 2 §3.10). Numeric columns become float64 ndarrays; string columns become JSON lists."""
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
    """Warn once per column whose values differ from frame 0's, mirroring the whole-file
    ``EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE`` warning (Part 2 §3.10): ``custom_per_atom`` is
    stored once per object, so a per-atom column that varies across frames cannot be represented
    losslessly and only frame 0's values are carried."""
    for name, array in atoms.arrays.items():
        if name in _RESERVED_ARRAYS:
            continue
        key = _namespace(name)
        if key in warned or key not in frame0_columns:
            continue
        current = np.asarray(array)
        reference = np.asarray(frame0_columns[key])
        if not np.array_equal(current, reference):
            warned.add(key)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="EXTXYZ_PER_FRAME_COLUMN_NOT_REPRESENTABLE",
                    message=(
                        f"per-atom column {name!r} varies across frames; the canonical model "
                        "stores per-atom custom arrays once per object (Part 2 §3.10), so only "
                        "the first frame's values are carried"
                    ),
                )
            )


def _is_per_atom_scalar(value: Any, n_atoms: int) -> bool:
    """True if ``value`` is a 1-D per-atom array (fits ArrayN); a non-collinear magmoms
    vector or an oddly-shaped array falls through to verbatim carry-through instead."""
    array = np.asarray(value)
    return array.ndim == 1 and array.shape[0] == n_atoms


def _as_json(value: Any) -> JsonValue:
    """Coerce an ASE info/calc value into a JSON-serialisable scalar or nested list."""
    if isinstance(value, np.ndarray):
        return value.tolist()  # type: ignore[no-any-return]
    if isinstance(value, np.generic):
        return value.item()  # type: ignore[no-any-return]
    return value  # type: ignore[no-any-return]
