"""VASP vasprun.xml parser (MASTER_SPEC Part 3 §3; v1.2 M42-S2).

The first **parser-only** format (S1's seam, D159): a DFT-*output* file that is never a
conversion *target*, so it registers a ``ParserPlugin`` with no ``ExporterPlugin`` and its
Capability Matrix row is read-side only. It is also the first format that reuses the shared
**VASP label-extraction core** (``parsers._vasp``, D160): the reader does the XML work and
hands the core parsed numbers, so M43's OUTCAR reader reuses the *identical* positions/cell/
energy/force mappings instead of co-discovering them.

**Streaming-first.** ``parse_stream`` is the real implementation and ``parse`` is defined as
``materialize(parse_stream(...))`` (the D56 one-code-path rule, as XDATCAR/ase_traj), so
whole-file and streamed readings cannot diverge. Reads with stdlib
``xml.etree.ElementTree.iterparse`` (D160 — a dedicated XML/VASP library was rejected: new
dependency weight for a parse job stdlib handles, D4/D7): the header is parsed eagerly and
each ``<calculation>`` (one per ionic step) is yielded lazily, with each processed element
cleared so peak memory tracks the resident step, not the file — vasprun.xml reaches XDATCAR's
10⁴-configuration scale for MD runs.

**Format facts handled at parse time and recorded, never guessed (Part 3 §5 rule 3):**

* The classical VASP layout (VASP ≤ 6.4): root ``<vasprun>`` (or ``<modeling.vasprun>``,
  VASP 5.4), an initial ``<structure name="initialpos">``, then one ``<calculation>`` block
  per ionic step carrying ``<energy>``, ``<varray name="forces">``, ``<varray name="stress">``
  and (for MD/relaxation) a per-step ``<structure>``. **VASP 6.5's new flat ``<modeling>``
  layout is refused** (``VASPRUN_UNSUPPORTED_LAYOUT``) rather than misread — never a silent
  misparse (P1).
* **Positions are direct (fractional)** — VASP writes vasprun.xml positions in scaled
  coordinates (ASE reads them as scaled), converted to Cartesian at the parser boundary using
  *that step's* lattice; a ``mode="cartesian"`` varray is read as-is. ``pbc = (T,T,T)`` by
  format definition, as a ``parse_notes`` entry.
* **Energy** — ``electronic.total_energy`` maps the ``<energy>`` block's ``e_0_energy``
  (VASP's energy extrapolated to zero smearing, the ``energy(sigma->0)`` value of OUTCAR),
  not the free energy ``e_fr_energy`` (D160; see the core). Every other energy-block scalar
  is carried verbatim per frame (never dropped, **P1**).
* **Per-step cells (NpT).** Each ``<calculation>``'s own ``<structure>`` supplies that step's
  cell and positions; a step without one reuses the previous step's — the fixed-cell form.

**Error contract (Part 3 §5; the ``VASPRUN_*`` code set, D160).** ``VASPRUN_EMPTY`` (empty
file or no ``<calculation>`` steps), ``VASPRUN_MALFORMED_XML`` (not well-formed XML, or a
non-vasprun root), ``VASPRUN_TRUNCATED`` (a killed job: the stream ends mid-``<calculation>``
after complete steps — full truncate-at-last-step *recovery* is M43/M44 territory, the
detection exists here), ``VASPRUN_UNSUPPORTED_LAYOUT`` (the VASP 6.5 flat ``<modeling>``
form), ``VASPRUN_MISSING_BLOCK`` (an expected block — ``<energy>``, ``forces``, the species
table, the initial structure — is absent: a ``ParseError``, never a defaulted field, P3),
``VASPRUN_UNMAPPED_TAG_CARRIED`` (unrecognised ``<i>``/``<v>``/``<varray>`` tags carried
verbatim, P1), and ``VASPRUN_MIXED_COORDINATE_MODE`` (a per-step structure in a different
coordinate mode than frame 0's — each step is still converted under its own mode).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance
from xtalate.parsers._vasp import (
    TOTAL_ENERGY_TAG,
    build_cell,
    forces,
    parse_notes_for,
    positions,
    stress_from_vasp_kbar,
    symbols_from_species,
    total_energy,
)
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Dynamics,
    Electronic,
    Frame,
    SimulationMetadata,
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

FORMAT_ID = "vasprun"
# The conventional VASP filename — a sniffing fact, like POSCAR/XDATCAR; the *format id* is the
# bare lowercase token used in `--format`/`--to` and provenance.source_format (D160).
CONVENTIONAL_NAME = "vasprun.xml"

# The classical root elements (VASP ≤ 6.4). VASP 6.5's flat layout uses a bare `<modeling>`
# root and is refused, never misread.
_CLASSICAL_ROOTS = frozenset({"vasprun", "modeling.vasprun"})

# Positions varrays are written in direct (fractional) coordinates; a `mode="cartesian"`
# attribute is the one exception (newer VASP). Anything else — including an absent attribute —
# is the format's direct default.
_CARTESIAN_MODE = "cartesian"

# The one <incar> tag mapped to a canonical home: the declared system name.
_SYSTEM_TAG = "SYSTEM"

_CARRY_KEY_PREFIX = "vasprun:"


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


def _carry_warning(name: str, *, location: str) -> ParseIssue:
    return ParseIssue(
        severity="warning",
        code="VASPRUN_UNMAPPED_TAG_CARRIED",
        message=(
            f"<{name}> has no canonical field; carried verbatim in "
            f"user_metadata.custom_per_frame['{_CARRY_KEY_PREFIX}{name}']"
        ),
        location=location,
    )


def _row_values(v: ET.Element, where: str) -> list[float]:
    """The float values of one ``<v>`` row, or a ``VASPRUN_MALFORMED_XML`` error.

    A ``<v>`` with no text or with non-numeric content is a malformed-file finding under
    the §5 contract, never a skipped row (P2) and never a defaulted value (P3).
    """
    text = v.text
    if text is None or not text.strip():
        raise _error("VASPRUN_MALFORMED_XML", f"{where} contains an empty <v>", location=where)
    try:
        return [float(x) for x in text.split()]
    except ValueError:
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"{where} holds non-numeric content: {text.strip()!r}",
            location=where,
        ) from None


def _varray_rows(varray: ET.Element) -> list[list[float]]:
    """The float rows of a ``<varray>`` (one ``[float, ...]`` per ``<v>`` child)."""
    where = f"<varray name={varray.get('name')!r}>"
    return [_row_values(v, where) for v in varray]


def _require_name(elem: ET.Element, where: str) -> str:
    """A walked tag's ``name`` attribute, or a malformed finding.

    VASP never writes unnamed ``<i>``/``<v>``/``<varray>`` tags in the walked blocks; an
    unnamed tag would be carried under a ``None`` key, so it is refused instead (P2: never
    skip silently — the refusal is the honest reading of a malformed file).
    """
    name = elem.get("name")
    if name is None:
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"<{elem.tag}> in {where} has no name attribute",
            location=where,
        )
    return name


def _scalar_float(elem: ET.Element) -> float | None:
    """The value of an ``<i>`` scalar, or ``None`` when the text does not parse as one float.

    ``None`` (not an error) for a tag whose value is not a plain scalar — the reader's caller
    decides whether that is a carry or a malformed-file finding.
    """
    text = elem.text
    if text is None:
        return None
    try:
        return float(text.strip())
    except ValueError:
        return None


def _read_program(generator: ET.Element) -> str | None:
    """The declared VASP program string (``<i name="program">``) → ``simulation.source_code``."""
    for i in generator.findall("i"):
        if i.get("name") == "program" and i.text is not None:
            return i.text.strip()
    return None


def _read_system(incar: ET.Element) -> str | None:
    """The declared ``SYSTEM`` label → ``simulation.extra['system']``."""
    for i in incar.findall("i"):
        if i.get("name") == _SYSTEM_TAG and i.text is not None:
            return i.text.strip()
    return None


def _read_species(atominfo: ET.Element) -> list[tuple[int, int]]:
    """Per-species ``(Z, count)`` from the atom-info blocks, in declared species order.

    The classical layout carries one ``<v>`` per species in ``<array name="atomtypes">``
    (fields ``mass Z psp``) and one ``<c>`` per atom in ``<array name="atoms">`` whose last
    column is the 1-based species index. Counts are derived from the atoms array and paired
    with the atomtypes Z column, so the symbols come from the element table (single source),
    never guessed. An atomtypes array without a ``Z`` field is a different VASP generation
    and falls through to the missing-species error rather than being guessed at.
    """
    z_by_index: dict[int, int] = {}
    for array in atominfo.findall("array"):
        name = array.get("name")
        if name == "atomtypes":
            fields = [(f.text or "").strip() for f in array.findall("field")]
            if "Z" not in fields:
                continue
            z_index = fields.index("Z")
            for n, v in enumerate(array.findall("v"), start=1):
                text = v.text
                if text is None or not text.strip():
                    raise _error(
                        "VASPRUN_MALFORMED_XML",
                        f"atomtypes row {n} has no content",
                        location="<atominfo>",
                    ) from None
                parts = text.split()
                try:
                    z_by_index[n] = int(float(parts[z_index]))
                except (IndexError, ValueError):
                    raise _error(
                        "VASPRUN_MALFORMED_XML",
                        f"atomtypes row {n} has no atomic-number value: {text.strip()!r}",
                        location="<atominfo>",
                    ) from None
        elif name == "atoms":
            index_counts: dict[int, int] = {}
            set_elem = array.find("set")
            if set_elem is not None:
                for c in set_elem.findall("c"):
                    parts = (c.text or "").split()
                    if len(parts) == 4:
                        try:
                            species_index = int(parts[3])
                        except ValueError:
                            continue
                        index_counts[species_index] = index_counts.get(species_index, 0) + 1
            species: list[tuple[int, int]] = []
            for index in sorted(z_by_index):
                count = index_counts.get(index)
                if count is None:
                    raise _error(
                        "VASPRUN_MALFORMED_XML",
                        f"atomtypes declares species {index} but the atoms array never "
                        "references it",
                        location="<atominfo>",
                    )
                species.append((z_by_index[index], count))
            return species
    return []


@dataclass
class _Structure:
    """One parsed ``<structure>``: the mapped cell/positions plus the unmapped carries."""

    lattice: np.ndarray | None
    positions: np.ndarray | None
    mode: str
    # Unmapped tags in the walked structure block: name -> scalar float or nested list.
    carries: dict[str, Any]


def _read_structure(elem: ET.Element, issues: list[ParseIssue], *, location: str) -> _Structure:
    """Read one ``<structure>``: basis → lattice, positions → raw rows + mode, and every
    other ``<i>``/``<varray>`` tag in the walked block carried verbatim (P1).

    The walked block is ``crystal`` (basis, volume, energy, rec_basis …) plus the
    structure-level varrays (positions, selective, velocities …). Unmapped tags are carried
    under ``vasprun:<name>`` with a ``VASPRUN_UNMAPPED_TAG_CARRIED`` warning — the extXYZ
    unmapped-column precedent; nothing inside a walked block is ever dropped silently.
    """
    lattice: np.ndarray | None = None
    positions_raw: np.ndarray | None = None
    mode = "direct"
    carries: dict[str, Any] = {}
    crystal = elem.find("crystal")
    if crystal is not None:
        for varray in crystal.findall("varray"):
            name = _require_name(varray, "<structure>/<crystal>")
            if name == "basis":
                lattice = _as_lattice(_varray_rows(varray))
            else:
                carries[name] = _varray_rows(varray)
        for i in crystal.findall("i"):
            value = _scalar_float(i)
            if value is not None:
                carries[_require_name(i, "<structure>/<crystal>")] = value
    for varray in elem.findall("varray"):
        name = _require_name(varray, "<structure>")
        if name == "positions":
            mode = varray.get("mode") or "direct"
            positions_raw = np.asarray(_varray_rows(varray), dtype=float)
        else:
            carries[name] = _varray_rows(varray)
    for name in carries:
        issues.append(_carry_warning(name, location=location))
    return _Structure(lattice=lattice, positions=positions_raw, mode=mode, carries=carries)


def _as_lattice(rows: list[list[float]]) -> np.ndarray:
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"basis varray must hold exactly 3 rows of 3 components, found {rows!r}",
            location="<structure>/<crystal>",
        )
    return np.asarray(rows, dtype=float)


def _read_energy(calc: ET.Element, frame_index: int) -> tuple[float, dict[str, Any]]:
    """The step's ``electronic.total_energy`` (``e_0_energy``) plus the other energy-block
    scalars carried verbatim per frame. A missing ``<energy>`` block or a missing
    ``e_0_energy`` is a ``ParseError`` (P3 — never a defaulted energy)."""
    energy = calc.find("energy")
    if energy is None:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            f"<calculation> {frame_index} has no <energy> block; electronic.total_energy "
            "cannot be populated (P3: absence is never defaulted)",
            location=f"frame {frame_index}",
        )
    total: float | None = None
    carries: dict[str, Any] = {}
    for i in energy.findall("i"):
        name = _require_name(i, "<energy>")
        value = _scalar_float(i)
        if name == TOTAL_ENERGY_TAG and value is not None:
            total = value
        elif value is not None:
            carries[name] = value
    for v in energy.findall("v"):
        name = _require_name(v, "<energy>")
        values = _row_values(v, "<energy>")
        if name == TOTAL_ENERGY_TAG and total is None and len(values) == 1:
            total = values[0]
        else:
            carries[name] = values[0] if len(values) == 1 else values
    if total is None:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            f"<calculation> {frame_index} has no scalar {TOTAL_ENERGY_TAG} in its <energy> "
            f"block (a spin-polarized two-component <v> is not mapped in v1.2; the canonical "
            "scalar total energy needs one value)",
            location=f"frame {frame_index}",
        )
    return total, carries


def _read_forces(calc: ET.Element, frame_index: int) -> np.ndarray:
    varray = next((v for v in calc.findall("varray") if v.get("name") == "forces"), None)
    if varray is None:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            f'<calculation> {frame_index} has no <varray name="forces">; dynamics.forces '
            "cannot be populated (P3: absence is never defaulted)",
            location=f"frame {frame_index}",
        )
    return forces(_varray_rows(varray))


def _read_stress(calc: ET.Element, frame_index: int) -> np.ndarray | None:
    """The step's ``electronic.stress`` — the ``<varray name="stress">`` tensor mapped
    deterministically (kBar, compression-positive → tension-positive eV/Å³, D161).

    ``None`` when the step carries no stress block: absence is information (many SCF-only
    runs have no stress unless ISIF requested it) and is **never** defaulted to a zero
    tensor (P3).
    """
    varray = next((v for v in calc.findall("varray") if v.get("name") == "stress"), None)
    if varray is None:
        return None
    rows = _varray_rows(varray)
    if len(rows) != 3 or any(len(row) != 3 for row in rows):
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f'<varray name="stress"> must hold exactly 3 rows of 3 components, found {rows!r}',
            location=f"frame {frame_index}",
        )
    return stress_from_vasp_kbar(rows)


@dataclass
class _Header:
    """Everything parsed eagerly before the first frame: object-level metadata and the
    initial structure that frames reuse when a step carries none of its own."""

    program: str | None
    system: str | None
    symbols: list[str]
    lattice: np.ndarray
    positions: np.ndarray
    mode: str
    sim_extra: dict[str, str]
    custom_global: dict[str, JsonValue]


def _read_header(context: Iterator[tuple[str, ET.Element]], issues: list[ParseIssue]) -> _Header:
    """Parse the document header and stop at the first ``<calculation>`` start.

    The ``context`` iterator is shared with the frame loop, which resumes from exactly this
    event — one pass, two phases. The root element is checked here so a foreign XML document
    (or VASP 6.5's flat ``<modeling>`` layout) is refused rather than misread.
    """
    program: str | None = None
    system: str | None = None
    species: list[tuple[int, int]] = []
    lattice: np.ndarray | None = None
    positions_raw: np.ndarray | None = None
    mode = "direct"
    sim_extra: dict[str, str] = {}
    custom_global: dict[str, JsonValue] = {}
    seen_root = False
    depth = 0
    for event, elem in context:
        if event == "start":
            depth += 1
            if not seen_root:
                seen_root = True
                if elem.tag == "modeling":
                    raise _error(
                        "VASPRUN_UNSUPPORTED_LAYOUT",
                        "this file uses VASP 6.5's flat <modeling> layout, which the "
                        "vasprun.xml parser does not yet read (it reads the classical "
                        "<vasprun>/<calculation> layout of VASP ≤ 6.4); refusing rather than "
                        "misreading it (P1)",
                    )
                if elem.tag not in _CLASSICAL_ROOTS:
                    raise _error(
                        "VASPRUN_MALFORMED_XML",
                        f"root element {elem.tag!r} is not a vasprun.xml document "
                        f"(expected {sorted(_CLASSICAL_ROOTS)})",
                    )
            if elem.tag == "calculation":
                # Stop here; the frame loop resumes from this very event.
                break
            continue
        # End events. Only root-level *sections* (depth 1 under the root) are processed and
        # then cleared. Descendants are never cleared here: their text is read when their
        # section's end event fires, and clearing a descendant early would wipe the data its
        # parent still needs. Clearing the section clears the whole subtree in one step, so
        # peak memory stays bounded by the largest unprocessed header section, not the file.
        depth -= 1
        if depth != 1:
            continue
        tag = elem.tag
        if tag == "generator":
            program = _read_program(elem)
        elif tag == "incar":
            system = _read_system(elem)
        elif tag == "atominfo":
            species = _read_species(elem)
        elif tag == "structure":
            structure = _read_structure(elem, issues, location='<structure name="initialpos">')
            if structure.lattice is not None:
                lattice = structure.lattice
            if structure.positions is not None:
                positions_raw = structure.positions
                mode = structure.mode
            for name, value in structure.carries.items():
                key = f"{_CARRY_KEY_PREFIX}{name}"
                if isinstance(value, float):
                    sim_extra[key] = str(value)
                else:
                    custom_global[key] = value
        elem.clear()
    else:
        # The document ended without any <calculation> block — no steps at all.
        raise _error("VASPRUN_EMPTY", "file contains no <calculation> steps")
    if not species:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            "no atom species found in <atominfo> (the classical atomtypes array with a Z "
            "column was not found)",
            location="<atominfo>",
        )
    if lattice is None:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            "no initial <structure> with a basis varray found before the first <calculation>",
        )
    if positions_raw is None:
        raise _error(
            "VASPRUN_MISSING_BLOCK",
            "the initial <structure> has no positions varray",
            location='<structure name="initialpos">',
        )
    try:
        symbols = symbols_from_species(species)
    except KeyError as exc:
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"<atominfo> declares an atomic number with no element symbol: {exc}",
            location="<atominfo>",
        ) from exc
    return _Header(
        program=program,
        system=system,
        symbols=symbols,
        lattice=lattice,
        positions=positions_raw,
        mode=mode,
        sim_extra=sim_extra,
        custom_global=custom_global,
    )


class _StepState:
    """The per-step geometry a frame is built from; updated by each step's own structure."""

    def __init__(self, header: _Header) -> None:
        self.symbols = header.symbols
        self.lattice = header.lattice
        self.positions = header.positions
        self.mode = header.mode


def _iter_calculations(
    context: Iterator[tuple[str, ET.Element]],
    header: _Header,
    issues: list[ParseIssue],
) -> Iterator[StreamFrame]:
    """Yield one ``StreamFrame`` per ``<calculation>``, lazily, holding one step resident."""
    state = _StepState(header)
    frame_index = 0
    for event, elem in context:
        if event != "end" or elem.tag != "calculation":
            continue
        yield _build_frame(elem, state, frame_index, issues)
        frame_index += 1
        elem.clear()


def _build_frame(
    calc: ET.Element, state: _StepState, frame_index: int, issues: list[ParseIssue]
) -> StreamFrame:
    """Build one frame from one complete ``<calculation>`` subtree.

    The step's own ``<structure>`` (if present) updates the geometry *before* the frame is
    built — VASP writes it at the end of the block, so at ``end`` time it holds this step's
    cell/positions; a step without one reuses the previous step's (the fixed-cell form).
    """
    total, energy_carries = _read_energy(calc, frame_index)
    force_rows = _read_forces(calc, frame_index)
    stress_tensor = _read_stress(calc, frame_index)
    structure = calc.find("structure")
    step_carries: dict[str, Any] = {}
    if structure is not None:
        parsed = _read_structure(structure, issues, location=f"frame {frame_index}")
        if parsed.lattice is not None:
            state.lattice = parsed.lattice
        if parsed.positions is not None:
            if parsed.mode != state.mode:
                issues.append(
                    ParseIssue(
                        severity="warning",
                        code="VASPRUN_MIXED_COORDINATE_MODE",
                        message=(
                            f"step {frame_index} writes its positions in "
                            f"{parsed.mode!r} but frame 0 is {state.mode!r}; each step is "
                            "still converted under its own mode, but "
                            "provenance.original_coordinate_system records frame 0's"
                        ),
                        location=f"frame {frame_index}",
                    )
                )
            state.mode = parsed.mode
            state.positions = parsed.positions
        step_carries.update(parsed.carries)

    n_atoms = len(state.symbols)
    if len(force_rows) != n_atoms:
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"step {frame_index} declares {len(force_rows)} force rows but the cell has "
            f"{n_atoms} atoms",
            location=f"frame {frame_index}",
        )
    positions_cart = positions(state.positions, state.lattice, mode=state.mode)
    if positions_cart.shape[0] != n_atoms:
        raise _error(
            "VASPRUN_MALFORMED_XML",
            f"step {frame_index} declares {positions_cart.shape[0]} positions but the cell "
            f"has {n_atoms} atoms",
            location=f"frame {frame_index}",
        )

    per_frame_custom: dict[str, Any] = {
        f"{_CARRY_KEY_PREFIX}{name}": value
        for name, value in {**energy_carries, **step_carries}.items()
    }
    # The structure carries already warned inside _read_structure; the energy-block scalars
    # warn here (they ride per frame, exactly like the structure ones).
    for name in energy_carries:
        issues.append(_carry_warning(name, location=f"frame {frame_index}"))

    frame = Frame(
        index=frame_index,
        atoms=AtomsBlock(symbols=list(state.symbols), positions=positions_cart),
        cell=build_cell(state.lattice),
        dynamics=Dynamics(forces=force_rows),
        electronic=Electronic(
            total_energy=total_energy(total),
            stress=stress_tensor,
        ),
    )
    return StreamFrame(frame=frame, per_frame_custom=per_frame_custom)


class VasprunParser(ParserPlugin):
    """VASP vasprun.xml reader (Part 3 §3; v1.2 M42-S2). Parser-only: never a conversion
    target (S1's seam, D159)."""

    format_id = FORMAT_ID
    format_name = "VASP vasprun.xml"
    version = "0.1.0"
    file_extensions = (".xml",)  # weak hint only; the <vasprun> root is the discriminator

    def sniff(self, head: bytes, filename: str | None) -> float:
        # VASP's exact conventional filename selects this reading (§6.1), like POSCAR/XDATCAR.
        if filename is not None and filename.lower() == CONVENTIONAL_NAME:
            return 1.0
        # Content: the root element is <vasprun> or <modeling.vasprun> (possibly after the
        # XML declaration). A bare ".xml" extension is far too weak to count on its own.
        text = head.decode("utf-8", errors="replace").lstrip()
        if text.startswith("<?xml"):
            end = text.find("?>")
            if end != -1:
                text = text[end + 2 :].lstrip()
        return 0.95 if text.startswith("<vasprun") or text.startswith("<modeling.vasprun") else 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56) — the
        streamed and whole-file readings are one code path and cannot diverge."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        """Header-eager, ``<calculation>``-lazy vasprun.xml parse (M12; Part 3 §2).

        stdlib ``iterparse`` streams the events; each processed element is cleared so peak
        memory tracks the resident ``<calculation>`` subtree, never the file — the property
        vasprun.xml (MD trajectories at 10⁴ configurations) exists to exercise. A malformed
        or truncated stream surfaces the matching ``VASPRUN_*`` error: malformed XML before
        any complete step is ``VASPRUN_MALFORMED_XML``; a stream that ends mid-``<calculation>``
        after complete steps is the killed-job ``VASPRUN_TRUNCATED`` (its *recovery* — keep
        the valid prefix — is M43/M44 territory, documented in D160).
        """
        # Peek the head so an empty/whitespace-only stream is the honest VASPRUN_EMPTY rather
        # than ElementTree's generic "no element found" (which we reserve for malformed text).
        head = stream.read(4096)
        if not head.strip():
            raise _error("VASPRUN_EMPTY", "file is empty")
        stream.seek(0)
        context = ET.iterparse(stream, events=("start", "end"))
        issues: list[ParseIssue] = []
        try:
            header = _read_header(context, issues)
        except ET.ParseError as exc:
            raise _error("VASPRUN_MALFORMED_XML", f"file is not well-formed XML: {exc}") from exc

        stream_header = _build_stream_header(header, filename)

        def _frames() -> Iterator[StreamFrame]:
            yielded = 0
            try:
                for frame in _iter_calculations(context, header, issues):
                    yielded += 1
                    yield frame
            except ET.ParseError as exc:
                if yielded == 0:
                    raise _error(
                        "VASPRUN_MALFORMED_XML", f"file is not well-formed XML: {exc}"
                    ) from exc
                raise _error(
                    "VASPRUN_TRUNCATED",
                    f"file ends mid-<calculation> after {yielded} complete ionic step(s): "
                    f"{exc}. The run appears to have been killed while writing; "
                    "truncate-at-last-complete-step recovery is M43/M44 territory, not yet "
                    "offered here (P3: no silent prefix).",
                ) from exc

        return FrameStream(stream_header, _frames(), issues=issues)

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
                "cell.lattice_vectors": FieldCapability(
                    level=full.level,
                    notes="Per-ionic-step cells are read from each <calculation>'s own "
                    "<structure> (the NpT form); a step without one reuses the previous "
                    "step's (the fixed-cell form).",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Always (T,T,T) by format definition; vasprun.xml carries no "
                    "explicit PBC.",
                ),
                "dynamics.forces": full,
                "electronic.total_energy": FieldCapability(
                    level=full.level,
                    notes="e_0_energy — VASP's energy extrapolated to zero smearing "
                    "(the energy(sigma->0) value of OUTCAR).",
                ),
                "electronic.stress": FieldCapability(
                    level=full.level,
                    notes="Deterministic mapping (D161): VASP declares its convention, so the "
                    "kBar compression-positive tensor is sign-flipped to canonical "
                    "tension-positive eV/Å³ and divided by the exact factor 1602.1766208; "
                    "recorded in parse_notes. A step without a stress block reads None "
                    "(P3 — never a defaulted zero tensor).",
                ),
                "simulation.extra": FieldCapability(
                    level=partial,
                    notes="Declared program string → simulation.source_code; SYSTEM → "
                    "extra['system']; unmapped header scalars carried as 'vasprun:<name>'.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=partial,
                    notes="Unmapped header arrays (e.g. rec_basis) carried as 'vasprun:<name>'.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=partial,
                    notes="Unmapped per-calculation tags (energy-block scalars, per-step "
                    "structure tags) carried as 'vasprun:<name>', one value per frame.",
                ),
            },
            max_frames=None,  # a trajectory: unbounded step count
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="both",
            lossy_notes=[],
        )


def _build_stream_header(header: _Header, filename: str | None) -> StreamHeader:
    """Assemble the object-level metadata from the eagerly-parsed header."""
    is_cartesian = header.mode == _CARTESIAN_MODE
    sim_extra = dict(header.sim_extra)
    if header.system is not None:
        sim_extra["system"] = header.system
    return StreamHeader(
        schema_version=SCHEMA_VERSION,
        provenance=build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian" if is_cartesian else "fractional",
            source_units={
                "positions": "angstrom" if is_cartesian else "fractional",
                "lattice_vectors": "angstrom",
                "stress": "kbar",
            },
            parse_notes=parse_notes_for(header.mode),
        ),
        # vasprun.xml numbers its steps but declares no per-step time axis (POTIM lives in
        # <incar>, not in a machine-readable trajectory field): absent, not invented (P3).
        trajectory=TrajectoryMetadata(timestep=None),
        simulation=SimulationMetadata(
            source_code=header.program,
            extra=sim_extra,
        ),
        custom_global=dict(header.custom_global),
    )


def make_vasprun_parser() -> VasprunParser:
    return VasprunParser()
