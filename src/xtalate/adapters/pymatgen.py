"""pymatgen in-memory adapters (v1.5 M57; DECISIONS.md D215/D216).

Two library functions between an in-memory pymatgen object and the Canonical Object:
``from_pymatgen(obj) -> CanonicalObject`` and ``to_pymatgen(canonical) ->
Structure | Molecule``. These are **not** a registered format — there is no file, so
there is no sniff, no capability row, and no ``ConversionReport``. P1 (nothing silently
dropped) is honored without a report surface by carrying every unmapped pymatgen payload
**verbatim** into ``user_metadata.custom_per_atom`` / ``custom_global`` under the
``pymatgen:<key>`` namespace (the extXYZ unmapped-column precedent), so ``to_pymatgen``
can restore it. Every value takes exactly one of three paths — mapped, laundered to
absence, or carried verbatim; there is no fourth path.

Like every wrapped library, the load-bearing work is **laundering pymatgen's
manufactured construction-time defaults back into absence** (P3; the ASE ``.traj``/
``.db`` discipline applied to a third wrapped library):

* **Periodicity.** The presence of a ``cell`` **is** the discriminator (D216): a periodic
  ``Structure`` maps its lattice to ``cell`` (with ``Lattice.pbc`` read faithfully, so a
  2D/slab's partial periodicity survives rather than being silently promoted to fully
  periodic); a lattice-less ``Molecule`` gets ``cell = None`` — never a fabricated identity
  lattice. ``to_pymatgen`` dispatches on the same fact: a celled Canonical Object becomes a
  ``Structure`` (restoring ``pbc``), a cell-less one a ``Molecule``. A multi-frame
  trajectory refuses (a pymatgen object is a single structure; reduce with
  ``frame_selection`` first).
* **Total charge / spin.** A ``Structure``'s public ``charge`` fabricates 0 or the
  oxidation-state sum whenever the caller never set one (its ``_charge`` sentinel stays
  ``None``); a ``Molecule``'s ``_charge`` is *always* populated (0 when defaulted), and
  its default ``spin_multiplicity`` is ``nelectrons % 2 + 1``. So: only a genuinely-set
  ``Structure`` charge is data; a ``Molecule`` charge is carried iff non-zero (an
  explicitly-passed 0 is indistinguishable from pymatgen's own manufactured 0 — the
  library cannot represent the distinction); a ``Molecule`` spin is carried iff it
  differs from the manufactured default. Neither has a canonical field (net charge and
  2S+1 multiplicity are not canonical quantities — ``electronic.total_spin`` holds S,
  not 2S+1), so both carry verbatim rather than being converted.
* **Oxidation states.** A species decorated with an oxidation state at construction is
  declared in-memory data: the state is stripped from the symbol (``Fe2+`` → ``Fe``)
  and carried per-site under ``custom_per_atom['pymatgen:oxidation_state']``.
* **Site properties.** ``site_properties`` starts empty, so presence means the caller set
  it: ``magmom`` → ``electronic.magnetic_moments``, per-site ``charge`` →
  ``electronic.charges``, ``velocities`` → ``dynamics.velocities`` (Å/fs — the VASP
  convention pymatgen's VASP tooling uses), everything else carried verbatim.
  ``selective_dynamics`` is carried rather than modelled as a ``fixed_atoms``
  constraint: its per-axis booleans would be silently flattened to whole-atom fixes.
* **Partial site occupancy.** Occupancy now takes the mapped path, not a silent fourth
  one (R6): a ``site.is_ordered`` site is full occupancy (absent a partial claim, P3),
  a *single-species* disordered site declares partial occupancy →
  ``atoms.occupancies`` (the CIF discipline: ``1.0`` for full sites, the fraction for
  partial ones, the field ``None`` only when nothing is partial); ``to_pymatgen``
  restores it as a per-site ``{species: fraction}`` dict. A site disordered across
  *multiple* species is refused, never silently reduced to one — ``atoms.occupancies``
  holds one number per atom, so there is no lossless canonical spelling for it.

Provenance records the wrapped library's version (D58/D59 precedent): the adapter stamps
``source_format = "pymatgen"`` (an in-memory source label, not a registered format id),
``original_coordinate_system = "fractional"`` for a ``Structure`` (pymatgen is
fractional-native, the CIF precedent) / ``"cartesian"`` for a ``Molecule``, and one
``operation = "parse"`` history entry whose ``parser_version`` folds in the pymatgen
version.

pymatgen ships no usable type information (like ASE/boto3, D7) — the mypy override skips
its imports, and every value read off a pymatgen object is converted to a concrete type
here so ``Any`` never escapes this module.
"""

from __future__ import annotations

from importlib.metadata import version as _dist_version
from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import JsonValue

from xtalate import __version__
from xtalate._time import utc_now as _utc_now
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Cell,
    ConversionRecord,
    Dynamics,
    Electronic,
    Frame,
    Provenance,
    UserMetadata,
)
from xtalate.schema.paths import is_full_occupancy

if TYPE_CHECKING:
    from pymatgen.core import Molecule, Structure

_KEY_PREFIX = "pymatgen:"
_SOURCE_FORMAT = "pymatgen"
#: site_properties keys with a dedicated canonical home (see the module docstring);
#: everything else carries verbatim. selective_dynamics is deliberately NOT here — its
#: per-axis booleans cannot be modelled losslessly as fixed_atoms constraints.
_MAPPED_SITE_PROPERTIES = frozenset({"magmom", "charge", "velocities"})
_OXI_STATE_KEY = f"{_KEY_PREFIX}oxidation_state"
_CHARGE_KEY = f"{_KEY_PREFIX}charge"
_SPIN_KEY = f"{_KEY_PREFIX}spin_multiplicity"


def _require_pymatgen() -> None:
    """Lazily import pymatgen (D4: consumed at this seam, never a dependency), raising a
    clear error naming the extra when it is absent."""
    try:
        import pymatgen.core  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "pymatgen is required for the pymatgen adapters; install xtalate[pymatgen]"
        ) from exc


def _pymatgen_version() -> str:
    # pymatgen exposes no module-level __version__ (checked against 2026.x); the installed
    # distribution version is the same string a pin bump moves.
    return _dist_version("pymatgen")


# --- from_pymatgen ---------------------------------------------------------------------


def from_pymatgen(obj: Any) -> CanonicalObject:
    """Build a Canonical Object from an in-memory pymatgen ``Structure`` (periodic) or
    ``Molecule`` (non-periodic). There is no report surface: anything without a canonical
    home carries verbatim under ``pymatgen:<key>`` instead of being dropped (P1)."""
    _require_pymatgen()
    if getattr(obj, "lattice", None) is not None:
        return _from_structure(obj)
    return _from_molecule(obj)


def _read_sites(
    source: Any,
) -> tuple[list[str], list[float | None], bool, list[float | None] | None]:
    """Symbols (oxidation decorations stripped), the declared per-site oxidation states, and
    partial site occupancies. A site that ``is_ordered`` is full occupancy — absence of a
    partial claim (P3); a *single-species* disordered site (``Fe:0.8``) declares partial
    occupancy, which maps onto ``atoms.occupancies`` (one number per atom); a site disordered
    across **multiple** species is refused — ``atoms.occupancies`` holds one occupancy per
    atom, so there is no lossless spelling for it, and silently keeping one species would be
    a P1 drop. The parallel occupancy list is ``None`` unless some site is genuinely partial
    (never a fabricated all-full list)."""
    symbols: list[str] = []
    oxi_states: list[float | None] = []
    occupancies: list[float | None] = []
    has_oxi_state = False
    has_partial = False
    for site in source.sites:
        if site.is_ordered:
            specie = site.specie
            symbols.append(str(specie.symbol))
            state: float | None = getattr(specie, "oxi_state", None)
            occ = 1.0
        else:
            composition = site.species
            if len(composition) != 1:
                raise ValueError(_disordered_refusal(composition))
            ((element, fraction),) = composition.items()
            symbols.append(element.symbol)
            state = getattr(element, "oxi_state", None)
            occ = float(fraction)
        oxi_states.append(state)
        if state is not None:
            has_oxi_state = True
        if not is_full_occupancy(occ):
            has_partial = True
        occupancies.append(occ)
    # A parallel occupancy list only when some site is genuinely partial; otherwise the
    # field stays None (absence of any partial claim) — never a fabricated all-full list.
    return symbols, oxi_states, has_oxi_state, occupancies if has_partial else None


def _disordered_refusal(composition: Any) -> str:
    """The clear refusal message for a mixed-species disordered pymatgen site — the PMG-2
    replacement for pymatgen's raw ``AttributeError`` on ``site.specie``."""
    from pymatgen.core import Composition

    if isinstance(composition, Composition):
        spell = composition.formula
    else:
        spell = str(composition)
    return (
        f"a pymatgen site is disordered across multiple species ({spell}); the Canonical "
        "Object's atoms.occupancies holds one occupancy per atom, so mixed-species disorder "
        "has no lossless representation — refusing rather than silently keeping one species "
        "or fabricating occupancies (P1)"
    )


def _read_site_properties(
    source: Any, custom_per_atom: dict[str, Any]
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    """Split ``site_properties`` into the three mapped arrays (charges, magmoms,
    velocities) plus verbatim carries into ``custom_per_atom``."""
    charges: np.ndarray | None = None
    magmoms: np.ndarray | None = None
    velocities: np.ndarray | None = None
    for key, value in dict(source.site_properties).items():
        if key == "magmom":
            magmoms = np.asarray(value, dtype=np.float64)
        elif key == "charge":
            charges = np.asarray(value, dtype=np.float64)
        elif key == "velocities":
            velocities = np.asarray(value, dtype=np.float64)
        else:
            # selective_dynamics rides here too: its per-axis booleans have no lossless
            # canonical home (fixed_atoms would flatten whole-atom fixes), so every
            # unmapped property carries verbatim rather than being modelled or dropped.
            custom_per_atom[f"{_KEY_PREFIX}{key}"] = _as_json(value)
    return charges, magmoms, velocities


def _from_structure(structure: Any) -> CanonicalObject:
    """The periodic case: lattice mapped to ``cell`` (never absent, never fabricated);
    only a caller-set total charge is data (pymatgen fabricates 0/the oxi-state sum)."""
    symbols, oxi_states, has_oxi_state, occupancies = _read_sites(structure)
    positions = np.asarray(structure.cart_coords, dtype=np.float64)

    custom_per_atom: dict[str, Any] = {}
    if has_oxi_state:
        custom_per_atom[_OXI_STATE_KEY] = oxi_states
    charges, magmoms, velocities = _read_site_properties(structure, custom_per_atom)

    custom_global: dict[str, JsonValue] = {}
    explicit_charge = getattr(structure, "_charge", None)
    if explicit_charge is not None:
        custom_global[_CHARGE_KEY] = float(explicit_charge)

    # Periodicity is read from the lattice, never assumed full: a 2D/slab Structure carries
    # e.g. (True, True, False), and overwriting it to fully periodic would be a silent
    # alteration of scientific information (P1/P3).
    pbc = structure.lattice.pbc
    return _assemble(
        symbols=symbols,
        positions=positions,
        cell=Cell(
            lattice_vectors=np.asarray(structure.lattice.matrix, dtype=np.float64),
            pbc=(bool(pbc[0]), bool(pbc[1]), bool(pbc[2])),
        ),
        original_coordinate_system="fractional",
        occupancies=occupancies,
        charges=charges,
        magmoms=magmoms,
        velocities=velocities,
        custom_global=custom_global,
        custom_per_atom=custom_per_atom,
    )


def _from_molecule(molecule: Any) -> CanonicalObject:
    """The non-periodic case (D216): ``cell = None`` — never an identity lattice — with
    the ``Molecule``-specific charge/spin manufactures laundered (see module docstring)."""
    symbols, oxi_states, has_oxi_state, occupancies = _read_sites(molecule)
    positions = np.asarray(molecule.cart_coords, dtype=np.float64)

    custom_per_atom: dict[str, Any] = {}
    if has_oxi_state:
        custom_per_atom[_OXI_STATE_KEY] = oxi_states
    charges, magmoms, velocities = _read_site_properties(molecule, custom_per_atom)

    custom_global: dict[str, JsonValue] = {}
    if float(molecule._charge) != 0.0:  # noqa: SLF001 — the sentinel IS the audit
        custom_global[_CHARGE_KEY] = float(molecule._charge)
    default_spin = int(molecule.nelectrons) % 2 + 1
    if int(molecule._spin_multiplicity) != default_spin:  # noqa: SLF001
        custom_global[_SPIN_KEY] = int(molecule._spin_multiplicity)

    return _assemble(
        symbols=symbols,
        positions=positions,
        cell=None,
        original_coordinate_system="cartesian",
        occupancies=occupancies,
        charges=charges,
        magmoms=magmoms,
        velocities=velocities,
        custom_global=custom_global,
        custom_per_atom=custom_per_atom,
    )


def _assemble(
    *,
    symbols: list[str],
    positions: np.ndarray,
    cell: Cell | None,
    original_coordinate_system: str,
    occupancies: list[float | None] | None,
    charges: np.ndarray | None,
    magmoms: np.ndarray | None,
    velocities: np.ndarray | None,
    custom_global: dict[str, JsonValue],
    custom_per_atom: dict[str, Any],
) -> CanonicalObject:
    """One single-frame Canonical Object from one pymatgen object — the shared tail of
    both mappings, so the two paths cannot diverge in framing or stamping."""
    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=symbols, positions=positions, occupancies=occupancies),
                cell=cell,
                dynamics=Dynamics(velocities=velocities),
                electronic=Electronic(charges=charges, magnetic_moments=magmoms),
            )
        ],
        provenance=_build_provenance(original_coordinate_system=original_coordinate_system),
        user_metadata=UserMetadata(custom_global=custom_global, custom_per_atom=custom_per_atom),
    )


# --- to_pymatgen -------------------------------------------------------------------------


def to_pymatgen(canonical: CanonicalObject) -> Structure | Molecule:
    """Build a pymatgen ``Structure`` or ``Molecule`` from a single-frame Canonical
    Object — dispatched on ``cell`` presence (D216): celled → ``Structure``, cell-less →
    ``Molecule`` (never a fabricated identity lattice for a molecule). Carried
    ``pymatgen:<key>`` payloads restore; a trajectory refuses honestly — pymatgen holds a
    single structure, never a silent frame-0 slice."""
    _require_pymatgen()
    from pymatgen.core import Lattice, Molecule, Structure

    if len(canonical.frames) != 1:
        raise ValueError(
            f"a pymatgen Structure/Molecule is a single structure; this object has "
            f"{len(canonical.frames)} frames — select one first (frame_selection)"
        )
    frame = canonical.frames[0]
    um = canonical.user_metadata
    sites = _restore_species(frame, um)

    if frame.cell is not None:
        structure = Structure(
            lattice=Lattice(frame.cell.lattice_vectors.tolist(), pbc=frame.cell.pbc),
            species=sites,
            coords=frame.atoms.positions.tolist(),
            coords_are_cartesian=True,
            site_properties=_restore_site_properties(frame, um),
        )
        carried_charge = um.custom_global.get(_CHARGE_KEY)
        if carried_charge is not None:
            structure.set_charge(_numeric_carry(carried_charge, _CHARGE_KEY))
        return structure

    kwargs: dict[str, Any] = {
        "species": sites,
        "coords": frame.atoms.positions.tolist(),
        "site_properties": _restore_site_properties(frame, um),
    }
    carried_charge = um.custom_global.get(_CHARGE_KEY)
    if carried_charge is not None:
        kwargs["charge"] = _numeric_carry(carried_charge, _CHARGE_KEY)
    carried_spin = um.custom_global.get(_SPIN_KEY)
    if carried_spin is not None:
        kwargs["spin_multiplicity"] = _numeric_carry(carried_spin, _SPIN_KEY)
    # With fractional species the caller never declared a charge/spin, pymatgen derives its
    # own default spin from the faux (fractional) electron count and its `charge_spin_check`
    # then rejects the honest restoration as "impossible". That check guards *declared* charge
    # vs spin; restoring fractional species is not a charge/spin claim, so it is suppressed
    # only on this genuine partial-occupancy path (a fully-ordered molecule keeps it on).
    if _any_partial_occupancy(frame):
        kwargs["charge_spin_check"] = False
    return Molecule(**kwargs)


def _any_partial_occupancy(frame: Frame) -> bool:
    """True when some site's ``atoms.occupancies`` value is not full — the signal that
    fractional species are being restored (see the ``charge_spin_check`` gating)."""
    return frame.atoms.occupancies is not None and any(
        not is_full_occupancy(value) for value in frame.atoms.occupancies
    )


def _numeric_carry(value: JsonValue, key: str) -> float:
    """A numeric carry must actually be a number — refuse loudly rather than coerce."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} carry must be a number; got {type(value).__name__}")
    return float(value)


def _restore_species(frame: Frame, um: UserMetadata) -> list[Any]:
    """Re-decorate species with carried oxidation states (bare element symbols where none
    was declared) and restore partial site occupancy. A site whose ``atoms.occupancies``
    value is not full becomes a per-site ``{species: fraction}`` dict — pymatgen's native
    spelling of a partially-occupied site (the PMG-1 inverse of reading ``Fe:0.8``). Full
    occupancy (``1.0``, or the field absent) stays a bare species; a per-site ``None`` — an
    *unknown* occupancy, CIF '?' — is refused: pymatgen has no way to express it without
    fabricating a fraction the source withheld (**P4**), and writing it as full would
    silently change the chemistry."""
    from pymatgen.core import Species

    oxi_states = um.custom_per_atom.get(_OXI_STATE_KEY)
    occupancies = frame.atoms.occupancies
    sites: list[Any] = []
    for i, symbol in enumerate(frame.atoms.symbols):
        state = oxi_states[i] if oxi_states is not None else None
        species = Species(symbol, state) if state is not None else symbol
        if occupancies is not None and not is_full_occupancy(occupancies[i]):
            occ = occupancies[i]
            if occ is None:
                raise ValueError(
                    f"atoms.occupancies[{i}] is None (an unknown occupancy); a pymatgen "
                    "object cannot represent it without fabricating a fraction the source "
                    "withheld — refuse rather than silently treat it as fully occupied (P4)"
                )
            sites.append({species: float(occ)})
        else:
            sites.append(species)
    return sites


def _restore_site_properties(frame: Frame, um: UserMetadata) -> dict[str, Any]:
    """Invert the site-property/carry mapping: the three mapped arrays go back to their
    pymatgen site-property names, and every ``pymatgen:``-namespaced carry restores under
    its bare key. Foreign-namespace carries (other formats') stay out — they belong to
    those formats' own seams."""
    properties: dict[str, Any] = {}
    if frame.electronic.magnetic_moments is not None:
        properties["magmom"] = frame.electronic.magnetic_moments.tolist()
    if frame.electronic.charges is not None:
        properties["charge"] = frame.electronic.charges.tolist()
    if frame.dynamics.velocities is not None:
        properties["velocities"] = frame.dynamics.velocities.tolist()
    for key, value in um.custom_per_atom.items():
        # The oxidation-state carry is restored onto the species by _restore_species; it must
        # NOT also reappear as a site property the source never had (a round-trip infidelity).
        if key.startswith(_KEY_PREFIX) and key != _OXI_STATE_KEY:
            properties[key[len(_KEY_PREFIX) :]] = (
                value.tolist() if isinstance(value, np.ndarray) else value
            )
    return properties


def _build_provenance(*, original_coordinate_system: str) -> Provenance:
    """The adapter's provenance stamp (D58/D59 precedent): no file, so
    ``source_filename = None``; the in-memory source label is not a registered format id;
    the history folds the wrapped pymatgen version into ``parser_version``."""
    return Provenance(
        source_filename=None,
        source_format=_SOURCE_FORMAT,
        source_units={"positions": "angstrom"},
        original_coordinate_system=original_coordinate_system,
        parse_notes=[
            "read via the pymatgen adapter; pymatgen-manufactured defaults (fabricated "
            "total charge, undeclared site properties) laundered to absence (P3); "
            "unmapped payloads carried verbatim under 'pymatgen:<key>' (P1)."
        ],
        history=[
            ConversionRecord(
                timestamp=_utc_now(),
                operation="parse",
                source_format=_SOURCE_FORMAT,
                target_format=None,
                tool_version=__version__,
                parser_version=(f"pymatgen-adapter {__version__} (pymatgen {_pymatgen_version()})"),
                assumptions=[],
            )
        ],
    )


def _as_json(value: Any) -> JsonValue:
    """Coerce a pymatgen payload into a JSON-serialisable scalar or nested list."""
    if isinstance(value, np.ndarray):
        return value.tolist()  # type: ignore[no-any-return]
    if isinstance(value, np.generic):
        return value.item()  # type: ignore[no-any-return]
    return value  # type: ignore[no-any-return]
