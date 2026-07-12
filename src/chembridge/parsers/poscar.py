"""VASP POSCAR / CONTCAR parser (MASTER_SPEC Part 3 §3, §8.2).

Hand-rolled (DECISIONS.md D7): hand control over the selective-dynamics → ``Constraint``
mapping and the fractional→Cartesian conversion, and no pymatgen dependency. POSCAR and
CONTCAR are structurally the *same* format (Part 3 §6.1) — CONTCAR is just the name VASP
writes a POSCAR-shaped file to, optionally with a velocity / predictor-corrector tail — so
one implementation backs both, registered twice under two ``format_id``s that differ only
in their conventional filename and sniff bias.

Format-defined facts handled at parse time, recorded in ``parse_notes`` rather than guessed
(Part 3 §5 rule 3): full 3-D periodicity (``pbc = (T,T,T)``, §3 n.3) and the
fractional→Cartesian coordinate conversion (§4). A VASP-4 file (counts, no species line)
cannot supply the *required* ``atoms.symbols`` (Part 2 §3.3), so it is a **recoverable**
parse error carrying ``recovery_hint="supply_species"`` (§3 n.1) — never invented placeholder
elements.
"""

from __future__ import annotations

from typing import BinaryIO

import numpy as np
from pydantic import JsonValue

from chembridge.parsers._common import build_provenance, decode_text
from chembridge.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    Constraint,
    Dynamics,
    Frame,
    UserMetadata,
)
from chembridge.schema.elements import is_valid_symbol
from chembridge.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

_COMMENT_KEY = "poscar:comment"
# The scaling factor is folded into the lattice (§4) and recorded as a provenance note, not as a
# presence-bearing field (DECISIONS.md D34) — see the parse() assembly for the rationale.
_SCALE_NOTE_PREFIX = "scaling factor folded into lattice vectors (§4); source value: "
_PREDICTOR_KEY = "contcar:predictor_corrector"
_PBC_NOTE = (
    "pbc set to (true,true,true) per POSCAR format definition (format-defined, not assumed)."
)


def _error(
    code: str, message: str, *, location: str | None = None, hint: str | None = None
) -> ParseError:
    return ParseError(
        [
            ParseIssue(
                severity="error",
                code=code,
                message=message,
                location=location,
                recovery_hint=hint,
            )
        ]
    )


def _all_ints(tokens: list[str]) -> bool:
    """True if every token parses as an int — the VASP-4 signature (counts, no species)."""
    if not tokens:
        return False
    try:
        for t in tokens:
            int(t)
    except ValueError:
        return False
    return True


def _floats(line: str, code: str, location: str) -> list[float]:
    try:
        return [float(t) for t in line.split()]
    except ValueError as exc:
        raise _error(code, f"expected numeric values, found {line!r}", location=location) from exc


class PoscarParser(ParserPlugin):
    """POSCAR/CONTCAR reader. One class, two registrations (``poscar`` and ``contcar``).

    ``conventional_name`` is VASP's fixed filename for this reading (``POSCAR``/``CONTCAR``);
    an exact match returns sniff confidence 1.0 (Part 3 §6.1). On a nameless file both
    readings match structurally; ``base_score`` biases the tie (POSCAR wins a plain file,
    CONTCAR is preferred only when a velocity tail is present) while the ambiguity is still
    surfaced by the sniffer.
    """

    version = "0.1.0"

    def __init__(
        self,
        *,
        format_id: str = "poscar",
        conventional_name: str = "POSCAR",
        base_score: float = 0.6,
        tail_bonus: float = 0.0,
    ) -> None:
        self.format_id = format_id
        self.format_name = "VASP POSCAR" if format_id == "poscar" else "VASP CONTCAR"
        self.file_extensions = ()  # POSCAR/CONTCAR are conventional *names*, not extensions.
        self._conventional_name = conventional_name
        self._base_score = base_score
        self._tail_bonus = tail_bonus

    # -- sniff -------------------------------------------------------------------------

    def sniff(self, head: bytes, filename: str | None) -> float:
        if filename is not None and filename == self._conventional_name:
            return 1.0  # VASP's exact conventional name selects this reading (§6.1)
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) < 7:
            return 0.0
        # Structural signature: line 2 is a lone scale float, lines 3-5 are 3 floats each.
        try:
            float(lines[1].strip())
            for row in lines[2:5]:
                if len(row.split()) != 3:
                    return 0.0
                [float(t) for t in row.split()]
        except ValueError:
            return 0.0
        score = self._base_score
        if self._tail_bonus and self._has_velocity_tail(lines):
            # Only CONTCAR conventionally carries a velocity/predictor tail (§6.1 rule 2).
            score += self._tail_bonus
        return min(score, 1.0)

    @staticmethod
    def _has_velocity_tail(lines: list[str]) -> bool:
        # Heuristic used only for sniff biasing: a blank line followed by more content after
        # what looks like the coordinate block. Cheap and never authoritative.
        try:
            count_line = lines[6].split()
            n = sum(int(t) for t in count_line)
        except ValueError:
            return False
        # coords start ~line 8 (0-indexed 7 or 8 with a mode line); a tail is any content
        # well past n coordinate lines.
        return len([ln for ln in lines[8 + n :] if ln.strip()]) > 0

    # -- parse -------------------------------------------------------------------------

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        lines = decode_text(stream.read(), format_id=self.format_id).splitlines()
        if len(lines) < 7:
            raise _error("POSCAR_MALFORMED", "file is too short to be a POSCAR (need >= 7 lines)")

        issues: list[ParseIssue] = []
        title = lines[0].strip()

        # --- scaling factor (line 2) --------------------------------------------------
        scale_token = lines[1].strip()
        try:
            scale = float(scale_token)
        except ValueError as exc:
            raise _error(
                "POSCAR_MALFORMED",
                f"scaling factor is not numeric: {lines[1]!r}",
                location="line 2",
            ) from exc
        if scale == 0.0:
            raise _error("POSCAR_MALFORMED", "scaling factor must be non-zero", location="line 2")

        # --- lattice (lines 3-5) ------------------------------------------------------
        raw_rows = [_floats(lines[2 + k], "POSCAR_MALFORMED", f"line {3 + k}") for k in range(3)]
        for k, row in enumerate(raw_rows):
            if len(row) != 3:
                raise _error(
                    "POSCAR_MALFORMED",
                    f"lattice row must have 3 components, found {len(row)}",
                    location=f"line {3 + k}",
                )
        raw_lattice = np.asarray(raw_rows, dtype=float)
        # A negative scale is a target *volume*: multiplier makes det(lattice) == |scale| (§4).
        if scale < 0:
            det = float(np.linalg.det(raw_lattice))
            if det == 0.0:
                raise _error(
                    "POSCAR_MALFORMED", "degenerate lattice (zero volume)", location="line 3"
                )
            multiplier = (abs(scale) / abs(det)) ** (1.0 / 3.0)
        else:
            multiplier = scale
        lattice = multiplier * raw_lattice

        # --- species / counts (VASP 5 has a symbol line; VASP 4 does not) -------------
        line6 = lines[5].split()
        if _all_ints(line6):
            # VASP-4: counts with no species. symbols are required (§3.3) — recoverable error.
            raise _error(
                "POSCAR_MISSING_SPECIES",
                "VASP-4 POSCAR lists atom counts but no element symbols; species must be "
                "supplied before this file can be represented (Part 3 §3 n.1)",
                location="line 6",
                hint="supply_species",
            )
        species = line6
        for sym in species:
            if not is_valid_symbol(sym):
                raise _error(
                    "POSCAR_INVALID_SYMBOL",
                    f"unknown element symbol {sym!r} on the species line (Part 2 §3.3)",
                    location="line 6",
                )
        count_tokens = lines[6].split()
        if not _all_ints(count_tokens) or len(count_tokens) != len(species):
            raise _error(
                "POSCAR_MALFORMED",
                f"expected {len(species)} integer counts to match species {species}, "
                f"found {lines[6]!r}",
                location="line 7",
            )
        counts = [int(t) for t in count_tokens]
        symbols: list[str] = []
        for sym, c in zip(species, counts, strict=True):
            symbols.extend([sym] * c)
        n_atoms = len(symbols)

        # --- optional 'Selective dynamics' + coordinate-mode lines --------------------
        cursor = 7
        selective = False
        if cursor < len(lines) and lines[cursor].strip()[:1] in ("S", "s"):
            selective = True
            cursor += 1
        if cursor >= len(lines):
            raise _error("POSCAR_MALFORMED", "missing coordinate-mode line", location="end of file")
        mode_char = lines[cursor].strip()[:1].lower()
        # VASP rule (§4): a mode line beginning with C/c/K/k is Cartesian; *everything else* —
        # 'Direct', 'Fractional', a blank line, or garbage — is Direct (fractional). Keying only
        # off 'd' would silently misread a fractional file as Cartesian Å (undetectable corruption),
        # so Cartesian is the explicit case and fractional is the default.
        fractional = mode_char not in ("c", "k")
        if mode_char not in ("c", "k", "d"):
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="POSCAR_AMBIGUOUS_COORDINATE_MODE",
                    message=(
                        f"coordinate-mode line {lines[cursor]!r} does not begin with C/K "
                        "(Cartesian) or D (Direct); read as Direct/fractional per VASP's default "
                        "rule (§4)"
                    ),
                    location=f"line {cursor + 1}",
                )
            )
        cursor += 1

        # --- coordinates (+ optional selective-dynamics flags) ------------------------
        coords: list[list[float]] = []
        masks: list[list[bool]] = []
        for a in range(n_atoms):
            idx = cursor + a
            if idx >= len(lines) or lines[idx].strip() == "":
                raise _error(
                    "POSCAR_INCONSISTENT_ATOM_COUNT",
                    f"expected {n_atoms} coordinate lines (from counts {counts}) but only "
                    f"{a} are present",
                    location=f"line {idx + 1}",
                    hint="truncate_at_last_valid_frame",
                )
            parts = lines[idx].split()
            if len(parts) < 3:
                raise _error(
                    "POSCAR_MALFORMED",
                    f"coordinate line must have >= 3 components: {lines[idx]!r}",
                    location=f"line {idx + 1}",
                )
            try:
                coords.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError as exc:
                raise _error(
                    "POSCAR_MALFORMED",
                    f"non-numeric coordinate: {lines[idx]!r}",
                    location=f"line {idx + 1}",
                ) from exc
            if selective:
                flags = parts[3:6]
                if len(flags) != 3:
                    raise _error(
                        "POSCAR_MALFORMED",
                        "selective dynamics requires 3 T/F flags per atom, found "
                        f"{flags} on {lines[idx]!r}",
                        location=f"line {idx + 1}",
                    )
                masks.append([f.upper().startswith("T") for f in flags])
        cursor += n_atoms

        frac = np.asarray(coords, dtype=float)
        if fractional:
            positions = frac @ lattice  # cart = fx*a + fy*b + fz*c (rows of lattice are a,b,c)
            coord_system = "fractional"
            source_units = {"positions": "fractional", "lattice_vectors": "angstrom"}
            coord_note = "Direct coordinates converted to Cartesian using lattice matrix (§4)."
        else:
            positions = frac * multiplier  # Cartesian coordinates are scaled too (§4)
            coord_system = "cartesian"
            source_units = {"positions": "angstrom", "lattice_vectors": "angstrom"}
            coord_note = "Cartesian coordinates scaled by the scaling factor (§4)."

        # --- selective dynamics -> Constraint (Part 3 §3 n.7) -------------------------
        constraints: list[Constraint] | None
        if not selective:
            constraints = None  # source said nothing about constraints
        elif all(all(m) for m in masks):
            constraints = []  # present but all-T: explicitly unconstrained (distinct from None)
        else:
            constraints = [
                Constraint(
                    kind="selective_dynamics",
                    atom_indices=list(range(n_atoms)),
                    parameters={"mask": [list(m) for m in masks]},
                )
            ]

        # --- optional velocity / predictor-corrector tail (CONTCAR) -------------------
        velocities, predictor = self._parse_tail(lines, cursor, n_atoms)
        parse_notes = [coord_note, _PBC_NOTE, f"{_SCALE_NOTE_PREFIX}{scale_token}"]
        if velocities is not None:
            # VASP writes the velocity block in Å/fs — already the canonical velocity unit (§3.1) —
            # so it is stored verbatim, no conversion. Annotate the source unit and note the block
            # so a reader can see the velocities came from the file, not from a default (§2 rule 3).
            source_units["velocities"] = "angstrom/fs"
            parse_notes.append(
                "velocity block read from the CONTCAR tail in Å/fs "
                "(canonical unit; stored verbatim)."
            )
        custom_global: dict[str, JsonValue] = {_COMMENT_KEY: title}
        if predictor is not None:
            custom_global[_PREDICTOR_KEY] = predictor
            issues.append(
                ParseIssue(
                    severity="warning",
                    code="POSCAR_PREDICTOR_CORRECTOR_CARRIED",
                    message="predictor-corrector block has no canonical mapping; carried "
                    "verbatim in user_metadata.custom_global['contcar:predictor_corrector'] "
                    "(Part 3 §3 n.12)",
                )
            )

        cell = Cell(lattice_vectors=lattice, pbc=(True, True, True))
        dynamics = Dynamics(
            velocities=None if velocities is None else np.asarray(velocities, dtype=float),
            constraints=constraints,
        )
        # The scaling factor is *already folded into* the returned lattice vectors (§4), so it is
        # not independent source information the target must separately carry — per the routing
        # rule (MASTER_SPEC §6.1: simulation.extra holds it "only if not already reflected in the
        # reconstructed lattice"), it is recorded in provenance (excluded from field presence),
        # not simulation.extra. Storing it in simulation.extra made every POSCAR→POSCAR conversion
        # fail absence-conformance, since no exporter can carry simulation.* yet the re-parse always
        # re-derives a scale (DECISIONS.md D34).
        provenance = build_provenance(
            format_id=self.format_id,
            filename=filename,
            original_coordinate_system=coord_system,
            source_units=source_units,
            parse_notes=parse_notes,
        )
        canonical = CanonicalObject(
            frames=[
                Frame(
                    index=0,
                    atoms=AtomsBlock(symbols=symbols, positions=positions),
                    cell=cell,
                    dynamics=dynamics,
                )
            ],
            trajectory=None,  # a POSCAR is a single structure, no time axis (§3.2)
            provenance=provenance,
            user_metadata=UserMetadata(custom_global=custom_global),
        )
        return ParseResult(canonical=canonical, issues=issues)

    @staticmethod
    def _parse_tail(
        lines: list[str], cursor: int, n_atoms: int
    ) -> tuple[list[list[float]] | None, str | None]:
        """Read an optional velocity block and predictor-corrector remainder after the
        coordinates. Velocities are the first ``n_atoms`` rows of three floats (an optional
        single mode line is skipped); anything after them is carried verbatim (§3 n.12)."""
        # Skip a single blank separator line.
        i = cursor
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines):
            return None, None
        # An optional mode line (e.g. 'Cartesian') precedes the velocities in some writers.
        first = lines[i].split()
        if len(first) < 3:
            i += 1  # treat as a mode/label line
        velocities: list[list[float]] = []
        for _ in range(n_atoms):
            if i >= len(lines):
                break
            parts = lines[i].split()
            try:
                velocities.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except (ValueError, IndexError):
                break
            i += 1
        vel_out = velocities if len(velocities) == n_atoms else None
        if vel_out is None:
            i = cursor  # velocities not cleanly present; the whole tail is predictor data
        remainder = "\n".join(lines[i:]).strip("\n")
        predictor = remainder if remainder.strip() else None
        return vel_out, predictor

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "cell.lattice_vectors": full,
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Always (T,T,T) by format definition; POSCAR carries no explicit PBC.",
                ),
                "dynamics.velocities": full,
                "dynamics.constraints": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only per-axis fixed-atom masks (selective dynamics).",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Title line and CONTCAR predictor block."
                ),
            },
            max_frames=1,
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="both",
            lossy_notes=[],
        )


def make_poscar_parser() -> PoscarParser:
    return PoscarParser(format_id="poscar", conventional_name="POSCAR", base_score=0.6)


def make_contcar_parser() -> PoscarParser:
    # Marginally lower base so POSCAR wins a nameless tie; a velocity tail tips it to CONTCAR.
    return PoscarParser(
        format_id="contcar", conventional_name="CONTCAR", base_score=0.55, tail_bonus=0.1
    )
