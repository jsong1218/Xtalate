"""Quantum ESPRESSO pw.x input exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v1.4 M51-S1, D192/D193).

The write side of the QE input format, the exact inverse of ``parsers.qe_pw_in`` (M50): it turns
a single-configuration Canonical Object back into the text ``pw.x`` input a QE run reads with
``pw.x -in``. Registering it closes the M50 staging state — ``qe_pw_in`` becomes a full read+write
format, and the Capability Matrix flips to read+write automatically because it is
registry-derived. It carries the version's central honesty decision:

> **Xtalate writes calculation *structures*, not calculation *science*.**

A *runnable* pw.x input needs physics the Canonical Object legitimately lacks — a plane-wave
cutoff (``ecutwfc``), a k-point mesh, and pseudopotential files. This exporter writes the
structure (explicit ``CELL_PARAMETERS {angstrom}`` with ``ibrav = 0`` *always*, ``ATOMIC_POSITIONS
{angstrom}``, the ``ATOMIC_SPECIES`` table) and the syntactically required namelist shells with
only canonical-derivable entries, and raises ``QEIN_INCOMPLETE_INPUT`` naming every run-required
entry the assembled file still lacks — it invents **none** of them (no defaulted cutoff, no
defaulted mesh, no synthesized pseudopotential filename):

* **``ibrav = 0`` always.** The exporter writes explicit cell vectors and never reverse-derives an
  ``ibrav`` code — that would be symmetry *detection*, an analysis concern Xtalate does not do,
  and a classic silent-transformation trap (D43). Explicit vectors are exact and universal.
* **The fillable/un-fillable split inside ``ATOMIC_SPECIES``.** Mass has a legitimate generic fill
  (IUPAC standard atomic weights), so an absent ``atoms.masses`` is a write ``required_field``
  refused through the existing ``missing_masses`` scenario — the lammps_data precedent (D181),
  reused unchanged. A pseudopotential has **no** generic fill, so when the object carries none the
  exporter writes a placeholder token that cannot be mistaken for a real file
  (``__PSEUDOPOTENTIAL_NOT_PROVIDED__.UPF`` — no real pseudopotential library ships it, and pw.x
  fails loudly on it) and names it in ``QEIN_INCOMPLETE_INPUT``. It is never guessed into a
  plausible filename (which could silently match the wrong file in the run's ``pseudo_dir`` —
  silent bad science, P1/P4).
* **Carry-back only what the object holds.** Pseudopotentials (``qe:pseudopotentials``),
  ``K_POINTS`` and other unrecognized cards (``qe_pw_in:unmapped_cards``), carried namelist
  entries (``qe_pw_in:namelists``), and the verbatim ``ATOMIC_SPECIES`` table
  (``qe_pw_in:atomic_species``) are written back **only when present** — never fabricated onto a
  non-QE object (the M51 cut line). Recognized simulation context that M50 routed to
  ``simulation.extra`` (``calculation``, ``ecutwfc``/``ecutrho``/``conv_thr``/``degauss``/
  ``smearing``/``occupations``) is written back into the right namelist when present. The key
  strings come from the shared ``xtalate.sdk.qe`` spot — identical constants, never forked
  (terminology is binding; ``exporters`` is an independent layer from ``parsers`` under the
  import-linter contract, so the single shared spot is the ``sdk`` layer both may import).
  Structural entries the exporter computes itself (``ibrav``/``nat``/``ntyp``) win over
  any carried spelling.
* **A single configuration only — via ``frame_selection``, like POSCAR/lammps_data.** A pw.x input
  is one configuration, so the exporter declares ``max_frames=1``: a multi-frame (trajectory)
  object is not refused outright, the pre-flight offers the ``frame_selection`` recovery, one
  frame is chosen and the dropped rest recorded as an Assumption (P4) — what lets a relaxation
  *trajectory* become a single DFT setup. ``export_stream`` keeps a defensive one-frame backstop
  for a bypassed pre-flight.
* **The absence of a lattice is pre-flight territory, not a default.** ``cell.lattice_vectors``
  is a write ``required_field``, so a lattice-less object routes through the existing
  ``missing_lattice`` recovery — no home-grown cell default is invented.

**Streaming-first for one-code-path honesty, but single-block.** Mirroring ``lammps_data``,
``export`` is defined over ``export_stream``; but a pw.x input is one configuration, so
``export_stream`` asserts exactly one frame and writes a single block.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO

import numpy as np

from xtalate.sdk import (
    CapabilityLevel,
    ExporterPlugin,
    ExporterWarning,
    FieldCapability,
    FormatCapabilities,
    StreamFrame,
    StreamHeader,
    stream_of,
)
from xtalate.sdk.qe import (
    _ATOMIC_SPECIES_KEY,
    _CONSUMED_SYSTEM_KEYS,
    _NAMELISTS_KEY,
    _PSEUDOPOTENTIALS_KEY,
    _SIMULATION_EXTRA_KEYS,
    _UNMAPPED_CARDS_KEY,
    species_symbol,
)

FORMAT_ID = "qe_pw_in"

#: The placeholder pseudopotential token written when the object carries no pseudopotential for a
#: species. Deliberately unreadable as a real filename: no pseudopotential library ships it, and
#: pw.x will fail to open it loudly — the opposite of a plausible name, which could silently match
#: the wrong file in the run's ``pseudo_dir`` (P1/P4). Named in ``QEIN_INCOMPLETE_INPUT``.
_EMPTY_PSEUDOPOTENTIAL = "__PSEUDOPOTENTIAL_NOT_PROVIDED__.UPF"

#: The honest-incompleteness warning code (Part 3 §5; D193): the assembled file is structurally
#: complete but not yet runnable, and the message names every entry the user must supply.
_INCOMPLETE_INPUT = "QEIN_INCOMPLETE_INPUT"

#: The structural &system facts the exporter computes itself; a carried spelling of any of these
#: is never written back (the exporter is the authority on the structure it writes).
_STRUCTURAL_SYSTEM_KEYS = _CONSUMED_SYSTEM_KEYS  # ibrav/nat/ntyp are in the shared set


class QePwInExporter(ExporterPlugin):
    """Quantum ESPRESSO pw.x input writer (Part 3 §3; M51-S1)."""

    format_id = FORMAT_ID
    format_name = "Quantum ESPRESSO pw.x input"
    version = "0.1.0"

    def export(self, canonical: Any, stream: BinaryIO) -> None:
        """Whole-file write, defined as the streamed write over the object's own frames — so a
        streamed and a materialized export are one code path and cannot diverge (D56)."""
        frame_stream = stream_of(canonical)
        self.export_stream(frame_stream.header, frame_stream.frames(), stream)

    def supports_streaming(self) -> bool:
        # A pw.x input is a single configuration (max_frames=1); there is no per-frame streaming
        # benefit, and a multi-frame object is reduced to one frame by the frame_selection recovery
        # before export, so this is never a streaming target.
        return False

    def export_stream(
        self, header: StreamHeader, frames: Iterator[StreamFrame], stream: BinaryIO
    ) -> None:
        collected = list(frames)
        if len(collected) != 1:
            # The engine consults max_frames and offers the frame_selection recovery before export,
            # so this only fires if that guard is ever bypassed — a defensive backstop, not the
            # user-facing path.
            raise ValueError(
                "qe_pw_in: a pw.x input is a single configuration but the object being exported "
                f"has {len(collected)} frames; reduce to one frame via the frame_selection "
                "recovery rather than writing only one"
            )
        _write_block(stream, collected[0].frame, header)

    def export_warnings(self, canonical: Any) -> list[ExporterWarning]:
        """The honest-incompleteness hook (Part 4 §1 rule 3, D151): after assembling what *will*
        be written, enumerate the run-required pw.x entries the output still lacks — a plane-wave
        cutoff, a k-point specification, and a real pseudopotential file per species — and emit
        **one** ``QEIN_INCOMPLETE_INPUT`` warning naming them in plain language. Only what is
        actually missing is listed: a QE→QE round-trip of a complete input emits no warning. The
        hook feeds the Conversion Report through the existing engine plumbing
        (``exporter.export_warnings(canonical_out)``) — no engine edit."""
        header = stream_of(canonical).header
        frame = canonical.frames[0]
        labels = _distinct_labels(frame, header)
        sim_extra = _simulation_extra(header)

        missing: list[str] = []
        if "ecutwfc" not in sim_extra:
            missing.append(
                "no plane-wave cutoff (`ecutwfc`) was available in the source — supply one "
                "before running"
            )
        unmapped = header.custom_global.get(_UNMAPPED_CARDS_KEY)
        has_k_points = isinstance(unmapped, list) and any(
            isinstance(entry, dict) and entry.get("card") == "K_POINTS" for entry in unmapped
        )
        if not has_k_points:
            missing.append("no k-points were available — add a `K_POINTS` card")
        pseudos = header.custom_global.get(_PSEUDOPOTENTIALS_KEY)
        pseudo_missing = [
            label for label in labels if not (isinstance(pseudos, dict) and label in pseudos)
        ]
        if pseudo_missing:
            missing.append(
                "pseudopotential files were not provided for: "
                f"{', '.join(pseudo_missing)} — replace the placeholders"
            )
        if not missing:
            return []
        return [
            ExporterWarning(
                code=_INCOMPLETE_INPUT,
                message=(
                    "This pw.x input is structurally complete but not yet runnable: "
                    + "; ".join(missing)
                    + "."
                ),
            )
        ]

    def unrepresentable(self, canonical: Any) -> str | None:
        """Why a pw.x input cannot express ``canonical``'s *values*, or ``None`` when it can
        (Part 4 §1; D179). A returned string produces a clean ``UNREPRESENTABLE_VALUE`` refusal,
        never an export-time crash (P1). Two value-level facts the field-granular Capability
        Matrix cannot see are checked here, before export. (The multi-frame case is *not* one of
        them: the exporter declares ``max_frames=1`` so the pre-flight offers the
        ``frame_selection`` recovery — one frame is chosen and the rest recorded as an Assumption,
        never silently truncated — so by the time this runs the object is already one frame.)

        1. **One element symbol with more than one mass.** A pw.x input's ``ATOMIC_SPECIES`` table
           is keyed by species *label*, and the exporter writes one row per distinct label with a
           single mass — so atoms of one element carrying different masses (isotope labels) cannot
           be expressed without silently flattening them (the lammps_data Masses-table hazard).
        2. **Two species labels resolving to the same element.** The parser resolves every
           ``ATOMIC_SPECIES`` label to an element for ``atoms.symbols``, so the Canonical Object
           cannot distinguish two labels that resolve to one element (``Fe`` vs ``Fe1``); the
           exporter cannot recover which atom had which label and would silently merge the
           species — refused rather than collapsed (P1)."""
        frame = canonical.frames[0]
        clash = _mass_symbol_clash(frame)
        if clash is not None:
            symbol, m1, m2 = clash
            return (
                f"qe_pw_in: element {symbol!r} appears with more than one mass "
                f"({m1!r} and {m2!r} amu); a pw.x input's ATOMIC_SPECIES table is one row per "
                "species label with a single mass, so this distinction cannot be written without "
                "silently collapsing it"
            )
        header = stream_of(canonical).header
        table = header.custom_global.get(_ATOMIC_SPECIES_KEY)
        if isinstance(table, dict):
            label_by_symbol: dict[str, str] = {}
            for label in table:
                element, _ = species_symbol(str(label))
                if element is None:
                    continue
                if element in label_by_symbol and label_by_symbol[element] != str(label):
                    return (
                        "qe_pw_in: species labels "
                        f"{label_by_symbol[element]!r} and {str(label)!r} both resolve to "
                        f"element {element!r}; the parser collapses them into one atom symbol, "
                        "so the exporter cannot recover which atom carried which label — refused "
                        "rather than silently merging the species"
                    )
                label_by_symbol[element] = str(label)
        return None

    def capabilities(self) -> FormatCapabilities:
        none = FieldCapability(level=CapabilityLevel.NONE)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the ATOMIC_SPECIES/ATOMIC_POSITIONS species labels: the "
                        "source's own labels when the object carries the QE species table, else "
                        "the element symbols."
                    ),
                ),
                "atoms.positions": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Absolute Cartesian, written in angstrom (ATOMIC_POSITIONS {angstrom}).",
                ),
                "atoms.masses": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Written as the per-species mass column of ATOMIC_SPECIES; a pw.x input "
                        "needs masses, so an object without them is refused via missing_masses, "
                        "never invented."
                    ),
                ),
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes=(
                        "Always written as an explicit CELL_PARAMETERS {angstrom} block with "
                        "ibrav = 0 — never reverse-derived to an ibrav code (D43)."
                    ),
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "Only fully periodic (p p p): a pw.x input states no boundary condition; "
                        "the cell is an implicit periodic box the parser re-derives."
                    ),
                ),
                "cell.space_group": none,
                "dynamics.velocities": none,
                "dynamics.forces": none,
                "dynamics.constraints": none,
                "electronic.total_energy": none,
                "electronic.stress": none,
                "electronic.charges": none,
                "electronic.magnetic_moments": none,
                "simulation.*": none,
                "trajectory.timestep": none,
                "frame.time": none,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "The four QE carry keys (qe:pseudopotentials, qe_pw_in:namelists, "
                        "qe_pw_in:unmapped_cards, qe_pw_in:atomic_species) are written back; "
                        "other keys are dropped."
                    ),
                ),
                "user_metadata.custom_per_atom": none,
                "user_metadata.custom_per_frame": none,
            },
            # The writable metadata: the four QE carry keys the parser wrote (identical strings —
            # imported, never forked), so the pre-flight diff predicts no loss for
            # `qe_pw_in → qe_pw_in` while every other target predicts it (P1/P5).
            writable_custom_keys={
                "user_metadata.custom_global": [
                    _PSEUDOPOTENTIALS_KEY,
                    _NAMELISTS_KEY,
                    _UNMAPPED_CARDS_KEY,
                    _ATOMIC_SPECIES_KEY,
                ],
            },
            # A pw.x input is a single configuration, like POSCAR and lammps_data (all
            # max_frames=1): a multi-frame object is not refused outright but routed through the
            # `frame_selection` recovery, which picks one frame and records the dropped rest as an
            # Assumption (P4). The value-level `unrepresentable` hook owns only the facts the
            # frame count cannot express (one element with two masses, two labels resolving to one
            # element); `export_stream` keeps a defensive backstop.
            max_frames=1,
            required_fields=[
                "atoms.symbols",
                "atoms.positions",
                "cell.lattice_vectors",
                "atoms.masses",
            ],
            allows_open_boundaries=False,  # pw.x runs fully periodic; the cell states no boundaries
            representable_constraint_kinds=[],
            native_coordinate_system="cartesian",
            lossy_notes=[
                "cell.pbc is written only implicitly: a pw.x input states no boundary line (QE "
                "runs fully periodic), so a fully-periodic box round-trips as p-p-p but a "
                "non-periodic axis cannot be recorded.",
                "Simulation context (calculation, ecutwfc, ecutrho, conv_thr, degauss, smearing, "
                "occupations) is written back into its namelist only when the object carries it; "
                "the write plan drops the simulation container (reported as removed), so a "
                "non-QE object's foreign context is never reinterpreted or borrowed.",
            ],
        )


def _write_block(stream: BinaryIO, frame: Any, header: StreamHeader) -> None:
    """Write the one configuration as a complete pw.x input (Part 3 §3)."""
    symbols = list(frame.atoms.symbols)
    n_atoms = len(symbols)
    labels = _species_labels(frame, header, symbols)
    distinct = list(dict.fromkeys(labels))
    n_types = len(distinct)
    masses = _require_masses(frame)
    pseudos = header.custom_global.get(_PSEUDOPOTENTIALS_KEY)

    # --- namelists: the three required shells + any carried ions/cell/fcp shell ---------------
    # &system's structural facts (ibrav/nat/ntyp) are the exporter's, always written — never a
    # carried spelling; the recognized simulation context and the carried entries ride alongside.
    system_entries: dict[str, Any] = {"ibrav": 0, "nat": n_atoms, "ntyp": n_types}
    system_entries.update(_namelist_entries(header, "system"))
    _write_namelist(stream, "control", _namelist_entries(header, "control"), always=True)
    _write_namelist(stream, "system", system_entries)
    _write_namelist(stream, "electrons", _namelist_entries(header, "electrons"), always=True)
    for name, entries in _carried_namelists(header).items():
        if name not in ("control", "system", "electrons") and entries:
            _write_namelist(stream, name, entries)

    # --- ATOMIC_SPECIES: label  mass  pseudopotential -----------------------------------------
    lines: list[str] = ["ATOMIC_SPECIES"]
    for label in distinct:
        first = labels.index(label)
        mass = _fmt(masses[first])
        pseudo = pseudos.get(label) if isinstance(pseudos, dict) else None
        if pseudo is None:
            pseudo = _EMPTY_PSEUDOPOTENTIAL
        lines.append(f"   {label} {mass} {pseudo}")

    # --- ATOMIC_POSITIONS {angstrom} ----------------------------------------------------------
    lines.append("ATOMIC_POSITIONS {angstrom}")
    positions = np.asarray(frame.atoms.positions, dtype=float)
    for label, pos in zip(labels, positions, strict=True):
        lines.append(f"   {label} {_fmt(pos[0])} {_fmt(pos[1])} {_fmt(pos[2])}")

    # --- CELL_PARAMETERS {angstrom} (ibrav = 0 always, D43) -----------------------------------
    lattice = _require_cell(frame)
    lines.append("CELL_PARAMETERS {angstrom}")
    for row in lattice:
        lines.append(f"   {_fmt(row[0])} {_fmt(row[1])} {_fmt(row[2])}")

    # --- carried unrecognized cards (K_POINTS, …) verbatim ------------------------------------
    unmapped = header.custom_global.get(_UNMAPPED_CARDS_KEY)
    if isinstance(unmapped, list):
        for entry in unmapped:
            if not isinstance(entry, dict):
                continue
            card = str(entry.get("card", ""))
            unit = entry.get("unit")
            head = card + (f" {unit}" if isinstance(unit, str) and unit else "")
            lines.append(head)
            lines.extend(f"   {line}" for line in entry.get("lines", []))

    stream.write(("\n".join(lines) + "\n").encode("utf-8"))


def _namelist_entries(header: StreamHeader, name: str) -> dict[str, Any]:
    """The entries for one namelist shell: the recognized simulation context M50 routed to
    ``simulation.extra`` for this namelist, then the carried entries (``qe_pw_in:namelists``)
    minus the structural &system facts the exporter computes itself. The two sources cannot
    collide — the parser consumes the recognized keys out of the carry (no double-report)."""
    entries: dict[str, Any] = {}
    sim_extra = _simulation_extra(header)
    for key in _SIMULATION_EXTRA_KEYS.get(name, frozenset()):
        if key in sim_extra:
            entries[key] = sim_extra[key]
    for key, value in _carried_namelists(header).get(name, {}).items():
        if name == "system" and key in _STRUCTURAL_SYSTEM_KEYS:
            continue  # ibrav/nat/ntyp (and the ibrav spellings) are the exporter's to write
        entries[key] = value
    return entries


def _carried_namelists(header: StreamHeader) -> dict[str, dict[str, Any]]:
    carried = header.custom_global.get(_NAMELISTS_KEY)
    if isinstance(carried, dict):
        return {
            str(name): entries for name, entries in carried.items() if isinstance(entries, dict)
        }
    return {}


def _simulation_extra(header: StreamHeader) -> dict[str, str]:
    simulation = header.simulation
    if simulation is not None and simulation.extra:
        return dict(simulation.extra)
    return {}


def _species_labels(frame: Any, header: StreamHeader, symbols: list[str]) -> list[str]:
    """The per-atom species label to write: the source's own ``ATOMIC_SPECIES`` label when the
    object carries the QE species table (each label resolved to its element via the shared ``_qe``
    rule so the mapping symbol → label is well-defined), else the element symbol itself. The
    same-element-two-labels case is refused upstream by ``unrepresentable``, so the mapping is
    unambiguous here."""
    table = header.custom_global.get(_ATOMIC_SPECIES_KEY)
    if not isinstance(table, dict) or not table:
        return list(symbols)
    label_by_symbol: dict[str, str] = {}
    for label in table:
        symbol, _ = species_symbol(str(label))
        if symbol is not None:
            label_by_symbol.setdefault(symbol, str(label))
    return [label_by_symbol.get(symbol, symbol) for symbol in symbols]


def _distinct_labels(frame: Any, header: StreamHeader) -> list[str]:
    """The distinct species labels in first-appearance order — the rows the writer emits, and the
    per-species set the incompleteness warning names."""
    return list(dict.fromkeys(_species_labels(frame, header, list(frame.atoms.symbols))))


def _write_namelist(
    stream: BinaryIO, name: str, entries: dict[str, Any], *, always: bool = False
) -> None:
    """One namelist shell. ``always`` emits an empty shell (``&NAME`` + ``/``) — QE accepts an
    empty namelist, and the three standard shells are emitted even bare so the structural file
    reads as a conventional pw.x input; a carried ions/cell/fcp shell is written only when it has
    entries."""
    if not entries and not always:
        return
    stream.write(f"&{name.upper()}\n".encode())
    for key, value in entries.items():
        stream.write(f"   {_format_namelist_entry(str(key), value)},\n".encode())
    stream.write(b"/\n")


def _format_namelist_entry(key: str, value: Any) -> str:
    """One namelist entry as text. An indexed value (the jsonified ``{index: value}`` carry of an
    array key such as ``celldm(1)``) expands to one ``key(index) = value`` per index, sorted
    numerically; a scalar writes ``key = value``. Values are written so the parser's tokenizer
    re-reads exactly the same Python value — the exact-carry round-trip."""
    if isinstance(value, dict):
        ordered = sorted(value.items(), key=lambda item: int(item[0]))
        return ", ".join(f"{key}({index}) = {_write_value(item)}" for index, item in ordered)
    return f"{key} = {_write_value(value)}"


def _write_value(value: Any) -> str:
    """A namelist value as Fortran text: logicals as ``.true.``/``.false.``, ints verbatim, floats
    at full repr precision (the parser reads them back bit-identical), strings single-quoted so
    the tokenizer re-reads them as strings — a carried number-like *string* must not re-read as a
    number, or the carry's JSON type would change (str vs float)."""
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    text = str(value)
    if "'" in text or '"' in text:
        # The parser's tokenizer has no quote escaping, so a carried string containing a quote
        # cannot round-trip; refuse loudly rather than emit a file that re-reads differently.
        raise ValueError(f"qe_pw_in: cannot write namelist string containing a quote: {text!r}")
    return f"'{text}'"


def _require_cell(frame: Any) -> np.ndarray:
    if frame.cell is None or frame.cell.lattice_vectors is None:
        raise ValueError(
            "qe_pw_in requires cell.lattice_vectors and the frame has none; supply it via the "
            "missing_lattice recovery before export (Part 4 §3)"
        )
    return np.asarray(frame.cell.lattice_vectors, dtype=float)


def _require_masses(frame: Any) -> np.ndarray:
    masses = frame.atoms.masses
    if masses is None:
        raise ValueError(
            "qe_pw_in requires atoms.masses; supply it via the missing_masses recovery before "
            "export (Part 4 §3)"
        )
    return np.asarray(masses, dtype=float)


def _mass_symbol_clash(frame: Any) -> tuple[str, float, float] | None:
    """The first element symbol that appears with two different masses, or ``None``. A pw.x
    input's ATOMIC_SPECIES table is one row per species label with a single mass, so a clash is
    unrepresentable (checked before export by ``unrepresentable``)."""
    masses = frame.atoms.masses
    if masses is None:
        return None
    masses_array = np.asarray(masses, dtype=float)
    seen: dict[str, float] = {}
    for symbol, mass in zip(frame.atoms.symbols, masses_array, strict=True):
        if symbol in seen:
            if not np.isclose(seen[symbol], mass):
                return str(symbol), float(seen[symbol]), float(mass)
        else:
            seen[symbol] = float(mass)
    return None


def _fmt(x: float) -> str:
    return repr(float(x))


def make_qe_pw_in_exporter() -> QePwInExporter:
    return QePwInExporter()
