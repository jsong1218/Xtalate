"""ASE database (``.db``) parser (MASTER_SPEC Part 3 §3; v1.5 M55).

The fourth ASE-backed wrap, built exactly like ``parsers.ase_traj.py``: rows are read via
``ase.db``, then the library's manufactured defaults are laundered back to absence (**P3**).
A ``.db`` row is **one independent structure**; a **single-row** database parses through the
ordinary spine to one Canonical Object. A **multi-row** database refuses on the single-file
path with a recoverable ``ASEDB_MULTIPLE_ROWS`` naming its row count and the two honest
resolutions (``--recover asedb_row_selection=index,row=<i>`` picks one row; ``--batch`` fans
every row out to its own conversion, M55-S3) — a dataset is aggregation, never one Canonical
Object (MASTER_SPEC Part 6 preamble; the rows-as-frames-of-one-object alternative breaks the
constant-N invariant, Part 2 §3.2).

The laundering rules (each pinned by a golden test in ``tests/parsers/test_ase_db.py``),
mirroring ``ase_traj``:

* **Cell.** An all-zero 3×3 (no cell was written) → ``cell = None``. A real cell keeps ASE's
  ``pbc``.
* **Masses.** Present only when the source wrote a ``masses`` array (ASE can *derive* masses
  from atomic numbers, but a derived value is not source data).
* **Momenta / velocities.** Velocities are populated only when the source carried a
  ``momenta`` array, unit-converted from ASE's internal velocity unit to canonical Å/fs.
* **Charges / magnetic moments.** The persisted ``initial_charges`` / ``initial_magmoms``
  arrays map to ``electronic.charges`` / ``electronic.magnetic_moments`` (the both-present
  precedence identical to ``ase_traj``).
* **``.db``-specific manufactured metadata.** ASE-generated ``id``/``ctime``/``mtime``/``user``
  and an **empty** key-value dict are absence, never data.
* **Stress.** Carried verbatim, exactly like ``ase_traj`` (D18): ASE's sign convention cannot
  be reconciled with the canonical tension-positive convention without a source-declared
  choice, so stress rides in ``custom_per_frame['ase_db:stress']`` (the shared stress-carry
  key set, D163) rather than ``electronic.stress``.

**Key–value carry (the extXYZ / ``ase_traj`` unmapped precedent, verbatim).** Non-empty
per-row key-value pairs → ``user_metadata.custom_global['ase_db:<key>']`` (the same
``:``-aware ``_namespace`` helper), each with an ``ASEDB_KV_CARRIED`` warning; the row's
arbitrary ``data`` blob carries the same way under ``'ase_db:data'``. Nothing dropped, nothing
interpreted (Part 2 §6.1).

The ASE version is recorded in ``provenance.history[].parser_version`` (D59), so a pin bump
that changes parse behaviour is visible in every report. SQLite is the ecosystem-default ASE
db backend; the exotic backends (ASE's JSON flavor) are the M55 cut line — never the
laundering suite or the multi-row refusal.
"""

from __future__ import annotations

import re
import tempfile
from typing import Any, BinaryIO

import ase
import numpy as np
from ase import units as ase_units
from ase.db import connect
from pydantic import JsonValue

from xtalate import __version__
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Constraint,
    Dynamics,
    Electronic,
    Frame,
    UserMetadata,
)
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "ase_db"
_KEY_PREFIX = "ase_db:"
_STRESS_KEY = "ase_db:stress"
_CONSTRAINTS_KEY = "ase_db:constraints"
_DATA_KEY = "ase_db:data"
# SQLite magic at the head of every SQLite file; strong (but never authoritative — a non-ASE
# SQLite database is sniffed as ase_db and refused at parse with ASEDB_MALFORMED).
_SQLITE_MAGIC = b"SQLite format 3\x00"
# Per-atom arrays with a dedicated canonical home; the persisted per-row arrays are exactly the
# ASE `systems` columns (numbers/positions/masses/momenta/initial_charges/initial_magmoms), so —
# unlike .traj — there are no arbitrary custom columns to collect (custom arrays are not
# persisted by ase.db, D69-style).
_RESERVED_ARRAYS = frozenset(
    {"numbers", "positions", "masses", "momenta", "initial_charges", "initial_magmoms"}
)
# Calculator results with a unit- and sign-safe canonical home. Everything else ASE places on
# the calculator (stress, dipole, free_energy, …) is carried verbatim to custom_per_frame (P1,
# D18).
_MAPPED_CALC_KEYS = frozenset({"energy", "forces", "charges", "magmoms"})
# ASE's velocity unit is Å / (ASE time unit); ase.units.fs is "1 fs in ASE time", so multiplying
# an ASE-unit velocity by it yields Å/fs (mirrors extXYZ; the exporter divides by the same
# factor).
_VEL_ASE_TO_ANG_PER_FS: float = ase_units.fs
# The machine-readable row-count location grammar (mirrors `frame N` in sdk/results.py): the
# ASEDB_MULTIPLE_ROWS refusal carries `location="rows <n>"` so the batch fan-out (M55-S3) can
# read the row count without parsing prose.
_ROW_COUNT_LOCATION = re.compile(r"^rows (\d+)$")

#: parser_version string folding in the wrapped ASE version (D59).
_PARSER_VERSION = f"{FORMAT_ID}-parser {__version__} (ase {ase.__version__})"


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


class AseDbParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "ASE Database"
    version = "0.1.0"
    file_extensions = (".db",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # SQLite magic is a strong hint that this is *a* SQLite database — but not proof it is
        # an ASE one (the `systems` table + columns decide at parse). The extension is a weaker
        # hint; a stray .db name over non-SQLite bytes must not win. Never authoritative.
        if head.startswith(_SQLITE_MAGIC):
            return 0.9
        if filename is not None and filename.endswith(".db"):
            return 0.3
        return 0.0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Read the database's rows through ``ase.db``; a single-row database becomes one
        Canonical Object, a multi-row one refuses (recoverable ``ASEDB_MULTIPLE_ROWS``), and
        an empty one refuses ``ASEDB_EMPTY``. ``.db`` is SQLite, which ``ase.db`` opens only by
        real path, so the byte stream is spooled to a temporary file for the read (the
        conversion layer always hands this parser bytes)."""
        rows = self._read_rows(stream)
        if not rows:
            raise _error("ASEDB_EMPTY", "the database contains no rows")
        if len(rows) > 1:
            ids = ", ".join(str(rid) for rid, _ in rows)
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="ASEDB_MULTIPLE_ROWS",
                        message=(
                            f"this ASE database contains {len(rows)} rows (ids {ids}); the "
                            "single-file path accepts one structure — re-parse one row with "
                            "--recover asedb_row_selection=index,row=<i> (i is the 0-based row "
                            "in the ids listed above), or convert every row under --batch (each "
                            "row becomes its own per-row conversion)"
                        ),
                        location=f"rows {len(rows)}",
                        recovery_hint="asedb_multiple_rows",
                    )
                ]
            )
        return self._row_result(rows[0][1], filename)

    def parse_recover(
        self,
        stream: BinaryIO,
        *,
        filename: str | None,
        hint: str,
        choice: str,
        parameters: dict[str, object],
        recovery_context: object | None = None,
    ) -> ParseResult:
        """Resolve the ``asedb_multiple_rows`` hint (the ``asedb_row_selection`` scenario, M55):
        ``index,row=<i>`` re-parses exactly that one row — the ``frame_selection`` no-default
        logic applied to rows (which row survives changes the scientific meaning, P4). ``all``
        is the batch fan-out (M55-S3), never a single-file resolution into one object — naming
        it here refuses cleanly, re-raising the recoverable refusal."""
        if hint != "asedb_multiple_rows":
            raise NotImplementedError(f"ase_db parse_recover does not handle hint {hint!r}")
        if choice != "index":
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="ASEDB_MULTIPLE_ROWS",
                        message=(
                            "'all' rows is the --batch fan-out (each row becomes its own "
                            "per-row conversion); the single-file path accepts one structure — "
                            "use --batch, or select one row with index,row=<i>"
                        ),
                        recovery_hint="asedb_multiple_rows",
                    )
                ]
            )
        raw = (parameters or {}).get("row")
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="ASEDB_MULTIPLE_ROWS",
                        message=(
                            "asedb_row_selection 'index' needs a non-negative integer "
                            f"parameter row=<i>, got {raw!r}"
                        ),
                        recovery_hint="asedb_multiple_rows",
                    )
                ]
            )
        rows = self._read_rows(stream)
        if raw >= len(rows):
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="ASEDB_MULTIPLE_ROWS",
                        message=(
                            f"row {raw} is out of range: this database has {len(rows)} "
                            f"row(s) (ids {', '.join(str(r) for r, _ in rows)})"
                        ),
                        location=f"rows {len(rows)}",
                        recovery_hint="asedb_multiple_rows",
                    )
                ]
            )
        rid, row = rows[raw]
        result = self._row_result(row, filename)
        selected = ParseIssue(
            severity="warning",
            code="ASEDB_ROW_SELECTED",
            message=(
                f"row {rid} of {len(rows)} selected per asedb_row_selection=index,row={raw}; "
                "the other rows are not part of this conversion (use --batch for every row)"
            ),
        )
        return ParseResult(canonical=result.canonical, issues=[selected, *result.issues])

    # -- row reading + the single-row object ---------------------------------------------

    def _read_rows(self, stream: BinaryIO) -> list[tuple[int, Any]]:
        """Spool the stream to a temporary ``.db`` file and read every row via ``ase.db``,
        normalising ASE's many exception types to the ParseError contract (§5). Returns
        ``(row.id, AtomsRow)`` pairs in the database's insertion order (id order — ASE
        autoincrements; the ids are what the multi-row refusal lists)."""
        data = stream.read()
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                db = connect(tmp.name, use_lock_file=False)
            except Exception as exc:  # noqa: BLE001 — ASE raises many types; normalise
                raise _error(
                    "ASEDB_MALFORMED", f"could not open the file as an ASE database: {exc}"
                ) from exc
            try:
                return [(row.id, row) for row in db.select()]
            except Exception as exc:  # noqa: BLE001
                raise _error(
                    "ASEDB_MALFORMED", f"could not read the file as an ASE database: {exc}"
                ) from exc

    def _row_result(self, row: Any, filename: str | None) -> ParseResult:
        issues: list[ParseIssue] = []
        try:
            atoms = row.toatoms()
        except Exception as exc:  # noqa: BLE001
            raise _error(
                "ASEDB_MALFORMED", f"could not reconstruct the row's atoms: {exc}"
            ) from exc

        # Key–value carry: non-empty per-row key-value pairs + the arbitrary data blob ride
        # into custom_global under the ase_db: namespace (Part 2 §6.1), each with a warning —
        # nothing dropped, nothing interpreted. An empty kv dict is ASE's manufactured default
        # → absence (no entry, no warning).
        custom_global: dict[str, JsonValue] = {}
        for key, value in dict(row.key_value_pairs or {}).items():
            custom_global[_namespace(key)] = _as_json(value)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="ASEDB_KV_CARRIED",
                    message=(
                        f"key-value pair {key!r} carried verbatim in "
                        f"user_metadata.custom_global['{_KEY_PREFIX}{key}'] (unmapped — "
                        "carried, never interpreted, Part 2 §6.1)"
                    ),
                )
            )
        if row.data:
            custom_global[_DATA_KEY] = _as_json(row.data)
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="ASEDB_KV_CARRIED",
                    message=(
                        f"row data blob carried verbatim in user_metadata.custom_global"
                        f"['{_DATA_KEY}'] (ASE's arbitrary per-row payload — carried, never "
                        "interpreted, Part 2 §6.1)"
                    ),
                )
            )

        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=[
                f"read via ASE {ase.__version__} ase.db; ASE-manufactured defaults "
                "(zero cell, derived masses, zeroed momenta, generated id/ctime/mtime/user) "
                "laundered to absence (P3)."
            ],
            parser_version=_PARSER_VERSION,
        )

        mapped, carried = _partition_calc(atoms, len(atoms), issues)
        charges, magmoms = _electronic_arrays(atoms, mapped, issues, carried)
        constraints, carried_constraints = self._build_constraints(atoms, issues)
        per_frame_custom: dict[str, np.ndarray | list[JsonValue]] = {}
        for key, value in carried.items():
            # A single-row object has one frame, so per-frame customs are length-1 lists
            # (custom_per_frame's first dimension is the frame count, Part 2 §3.10).
            per_frame_custom[_namespace(key)] = [value]
        if carried_constraints:
            # The non-FixAtoms constraints the warning names are really carried (ASEDB-2,
            # review R4) — a JSON-serializable description per constraint, so the P1 report
            # is true and the data is recoverable from the object.
            per_frame_custom[_CONSTRAINTS_KEY] = [carried_constraints]

        frame = Frame(
            index=0,
            atoms=AtomsBlock(
                symbols=list(atoms.get_chemical_symbols()),
                positions=np.asarray(atoms.get_positions(), dtype=np.float64),
                masses=(
                    np.asarray(atoms.arrays["masses"], dtype=np.float64)
                    if "masses" in atoms.arrays
                    else None
                ),
            ),
            cell=self._build_cell(atoms),
            dynamics=Dynamics(
                velocities=_build_velocities(atoms),
                forces=mapped.get("forces"),
                constraints=constraints,
            ),
            electronic=Electronic(
                total_energy=mapped.get("energy"),
                charges=charges,
                magnetic_moments=magmoms,
            ),
        )
        canonical = CanonicalObject(
            frames=[frame],
            trajectory=None,
            provenance=provenance,
            user_metadata=UserMetadata(
                custom_global=custom_global, custom_per_frame=per_frame_custom
            ),
        )
        return ParseResult(canonical=canonical, issues=issues)

    @staticmethod
    def _build_cell(atoms: Any) -> Cell | None:
        """Launder ASE's zero-cell default: an all-zero 3×3 means no cell was written → None."""
        lattice = np.asarray(atoms.cell.array, dtype=float)
        if not lattice.any():
            return None
        pbc = (bool(atoms.pbc[0]), bool(atoms.pbc[1]), bool(atoms.pbc[2]))
        return Cell(lattice_vectors=lattice, pbc=pbc)

    @staticmethod
    def _build_constraints(
        atoms: Any, issues: list[ParseIssue]
    ) -> tuple[list[Constraint] | None, list[JsonValue]]:
        """Map ASE ``FixAtoms`` to ``Constraint(kind=\"fixed_atoms\")`` (D58), the ase_traj rule
        verbatim: an empty constraints list is a manufactured default → None; a non-FixAtoms
        class is carried with a warning rather than modelled (M14 cut line). The carry is
        **real** (ASEDB-2, review R4): the second return value is one JSON-serializable
        description per non-``FixAtoms`` constraint — class name + params — which the caller
        stores under ``custom_per_frame['ase_db:constraints']``, exactly the namespace the
        warning names."""
        constraints: list[Constraint] = []
        carried_constraints: list[JsonValue] = []
        for con in atoms.constraints:
            if type(con).__name__ == "FixAtoms":
                indices = [int(i) for i in np.asarray(con.index).ravel().tolist()]
                constraints.append(
                    Constraint(kind="fixed_atoms", atom_indices=indices, parameters={})
                )
            else:
                carried_constraints.append(_describe_constraint(con))
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="ASE_DB_CONSTRAINT_NOT_MODELLED",
                        message=(
                            f"ASE constraint {type(con).__name__!r} has no canonical mapping; "
                            f"carried verbatim in custom_per_frame[{_CONSTRAINTS_KEY!r}] "
                            "(only FixAtoms is modelled)"
                        ),
                    )
                )
        return constraints or None, carried_constraints

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
                    level=partial, notes="From the persisted initial_charges array."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="From the persisted initial_magmoms array."
                ),
                "electronic.stress": FieldCapability(
                    level=partial,
                    notes="Populated only when the stress sign convention is resolved via the "
                    "ambiguous_stress_convention recovery; until then stress is carried verbatim "
                    "in custom_per_frame['ase_db:stress'] (D18, D163; M55-S1).",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Per-row key-value pairs and the data blob under ase_db:<key>.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Carries calculator results verbatim, incl. stress (D18).",
                ),
            },
            max_frames=1,  # one row → one structure; a multi-row db refuses ASEDB_MULTIPLE_ROWS
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="cartesian",
            # M55-S1 (D18, D163): stress is carried through custom_per_frame until the sign
            # convention is resolved by the ambiguous_stress_convention recovery — never mapped
            # silently. `carried_field_keys` names the carry so the Validation Engine can
            # compare a planned field against the re-parsed value (D151).
            carried_field_keys={"electronic.stress": _STRESS_KEY},
            lossy_notes=[
                "stress carried verbatim in user_metadata.custom_per_frame['ase_db:stress'] "
                "rather than electronic.stress (sign convention).",
            ],
        )


def _namespace(key: str) -> str:
    """Tag a raw ASE key with the ``ase_db:`` namespace (Part 2 §6.1) unless it already carries
    a ``<format>:`` namespace (a cross-format key kept verbatim), mirroring
    ``parsers.extxyz._namespace`` / ``parsers.ase_traj._namespace``."""
    return key if ":" in key else f"{_KEY_PREFIX}{key}"


def _build_velocities(atoms: Any) -> np.ndarray | None:
    """Laundering: ASE synthesises zero momenta for a row that declared none, so only a real
    momenta array produces velocities (unit-converted ASE → Å/fs)."""
    if not atoms.has("momenta"):
        return None
    raw = np.asarray(atoms.get_velocities(), dtype=np.float64)
    return raw * _VEL_ASE_TO_ANG_PER_FS


def _partition_calc(
    atoms: Any, n_atoms: int, issues: list[ParseIssue]
) -> tuple[dict[str, Any], dict[str, JsonValue]]:
    """Split the row's ASE calculator results into (mapped, carried), mirroring ase_traj.

    ``mapped`` holds results with a unit- and sign-safe canonical home (energy → eV, forces →
    eV/Å, per-atom ``charges``/``magmoms`` → the canonical arrays). ``carried`` holds everything
    else — ``stress`` (sign convention unreconcilable, D18) and any unexpected key — routed
    verbatim to ``custom_per_frame`` so nothing ASE parsed is dropped silently (P1). An
    unexpected key warns."""
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
                        code="ASE_DB_UNMAPPED_RESULT_CARRIED",
                        message=f"calculator result {key!r} has no canonical field; carried "
                        f"verbatim in user_metadata.custom_per_frame['{_KEY_PREFIX}{key}']",
                    )
                )
    return mapped, carried


def _electronic_arrays(
    atoms: Any,
    mapped: dict[str, Any],
    issues: list[ParseIssue],
    carried: dict[str, JsonValue],
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Resolve ``electronic.charges`` / ``electronic.magnetic_moments`` from the persisted
    per-row ``initial_charges`` / ``initial_magmoms`` arrays (an input the source set), with the
    both-present precedence identical to ``ase_traj``: the source-written *array* wins the
    canonical slot; a calculator value that *also* carried it rides into ``custom_per_frame``
    rather than being silently dropped or overwriting (P1)."""

    def _resolve(array_key: str, calc_key: str, canonical: str) -> np.ndarray | None:
        array_val = (
            np.asarray(atoms.arrays[array_key], dtype=np.float64)
            if array_key in atoms.arrays
            else None
        )
        calc_val: np.ndarray | None = mapped.pop(canonical, None)
        if array_val is not None:
            if calc_val is not None:
                carried[calc_key] = _as_json(calc_val)
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="ASE_DB_CHARGE_MOMENT_BOTH_PRESENT",
                        message=(
                            f"both a per-atom {array_key!r} array and a calculator "
                            f"{calc_key!r} result are present; the array is mapped to "
                            f"electronic.{canonical} and the calculator value carried in "
                            f"custom_per_frame['{_KEY_PREFIX}{calc_key}']"
                        ),
                    )
                )
            return array_val
        return calc_val

    charges = _resolve("initial_charges", "charges", "charges")
    magmoms = _resolve("initial_magmoms", "magmoms", "magnetic_moments")
    return charges, magmoms


def _is_per_atom_scalar(value: Any, n_atoms: int) -> bool:
    """True if ``value`` is a 1-D per-atom array (fits ArrayN)."""
    array = np.asarray(value)
    return array.ndim == 1 and array.shape[0] == n_atoms


def _json_safe(value: Any) -> JsonValue:
    """Recursively coerce an ASE constraint-params value into JSON (numpy arrays/scalars to
    plain Python), mirroring ``_as_json`` one level deeper — ``todict()`` kwargs can nest."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return _as_json(value)


def _describe_constraint(con: Any) -> dict[str, JsonValue]:
    """A JSON-serializable description of a non-``FixAtoms`` ASE constraint — its class name
    plus ASE's own ``todict()`` params when the constraint provides them — the value the
    ``ASE_DB_CONSTRAINT_NOT_MODELLED`` warning names as carried, so the carry is real
    (ASEDB-2, review R4)."""
    try:
        raw = con.todict()
    except Exception:
        raw = None
    params: JsonValue = _json_safe(raw) if isinstance(raw, dict) else {}
    return {"class": type(con).__name__, "params": params}


def _as_json(value: Any) -> JsonValue:
    """Coerce an ASE row/calc value into a JSON-serialisable scalar or nested list."""
    if isinstance(value, np.ndarray):
        return value.tolist()  # type: ignore[no-any-return]
    if isinstance(value, np.generic):
        return value.item()  # type: ignore[no-any-return]
    return value  # type: ignore[no-any-return]


def make_ase_db_parser() -> AseDbParser:
    return AseDbParser()
