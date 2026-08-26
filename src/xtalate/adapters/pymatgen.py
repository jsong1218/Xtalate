"""pymatgen in-memory adapters (v1.5 M57; DECISIONS.md D215).

Two library functions between an in-memory pymatgen object and the Canonical Object:
``from_pymatgen(obj) -> CanonicalObject`` and ``to_pymatgen(canonical) -> Structure``.
These are **not** a registered format — there is no file, so there is no sniff, no
capability row, and no ``ConversionReport``. P1 (nothing silently dropped) is honored
without a report surface by carrying every unmapped pymatgen payload **verbatim** into
``user_metadata.custom_per_atom`` / ``custom_global`` under the ``pymatgen:<key>``
namespace (the extXYZ unmapped-column precedent), so ``to_pymatgen`` can restore it.
Every value takes exactly one of three paths — mapped, laundered to absence, or carried
verbatim; there is no fourth path.

Like every wrapped library, the load-bearing work is **laundering pymatgen's
manufactured construction-time defaults back into absence** (P3; the ASE ``.traj``/``
.db`` discipline applied to a third wrapped library):

* **Total charge.** A ``Structure``'s public ``charge`` is fabricated whenever it was not
  explicitly set — pymatgen reports either ``0`` or the oxidation-state sum. Only a
  charge the caller *set* (``set_charge``) is data: it carries to
  ``custom_global['pymatgen:charge']``; the fabricated default never enters the object.
* **Oxidation states.** A species decorated with an oxidation state at construction is
  declared in-memory data: the state is stripped from the symbol (``Fe2+`` → ``Fe``)
  and carried per-site under ``custom_per_atom['pymatgen:oxidation_state']``.
* **Site properties.** ``site_properties`` starts empty, so presence means the caller set
  it: ``magmom`` → ``electronic.magnetic_moments``, per-site ``charge`` →
  ``electronic.charges``, ``velocities`` → ``dynamics.velocities`` (Å/fs — the VASP
  convention pymatgen's VASP tooling uses), everything else carried verbatim.
  ``selective_dynamics`` is carried rather than modelled as a ``fixed_atoms``
  constraint: its per-axis booleans would be silently flattened to whole-atom fixes.
* **Lattice.** A periodic ``Structure`` has a lattice — mapped to ``cell`` with pymatgen's
  ``(True, True, True)`` pbc. A lattice-less object is not a ``Structure``; S2 adds the
  ``Molecule`` case where ``cell = None`` (never a fabricated identity lattice).

Provenance records the wrapped library's version (D58/D59 precedent): the adapter stamps
``source_format = "pymatgen"`` (an in-memory source label, not a registered format id),
``original_coordinate_system = "fractional"`` (pymatgen is fractional-native, the CIF
precedent), and one ``operation = "parse"`` history entry whose ``parser_version`` folds
in the pymatgen version.

pymatgen ships no usable type information (like ASE/boto3, D7) — the mypy override skips
its imports, and every value read off a pymatgen object is converted to a concrete type
here so ``Any`` never escapes this module. S1 handles the periodic ``Structure``;
``Molecule`` support and the ``to_pymatgen`` dispatch land in S2.
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


def from_pymatgen(obj: Structure | Molecule) -> CanonicalObject:
    """Build a Canonical Object from an in-memory pymatgen ``Structure`` (periodic).

    S1 handles the periodic case only; a lattice-less ``Molecule`` raises until S2 lands
    the ``cell = None`` mapping. There is no report surface: anything without a canonical
    home carries verbatim under ``pymatgen:<key>`` instead of being dropped (P1).
    """
    _require_pymatgen()
    lattice = getattr(obj, "lattice", None)
    if lattice is None:
        raise NotImplementedError(
            "from_pymatgen: non-periodic pymatgen objects (Molecule) are not supported yet; "
            "Molecule support lands in S2"
        )
    structure = obj

    symbols: list[str] = []
    oxi_states: list[float | None] = []
    has_oxi_state = False
    for site in structure.sites:
        specie = site.specie
        symbols.append(str(specie.symbol))
        state: float | None = getattr(specie, "oxi_state", None)
        if state is not None:
            has_oxi_state = True
        oxi_states.append(state)

    positions = np.asarray(structure.cart_coords, dtype=np.float64)

    custom_per_atom: dict[str, Any] = {}
    if has_oxi_state:
        custom_per_atom[_OXI_STATE_KEY] = oxi_states
    charges: np.ndarray | None = None
    magmoms: np.ndarray | None = None
    velocities: np.ndarray | None = None
    for key, value in dict(structure.site_properties).items():
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

    # Laundering: pymatgen's public `.charge` fabricates 0 / the oxidation-state sum when
    # the caller never set one (`_charge is None`). Only a genuinely-set total charge is
    # data; there is no canonical net-charge field, so it carries verbatim (P1).
    custom_global: dict[str, JsonValue] = {}
    explicit_charge = getattr(structure, "_charge", None)
    if explicit_charge is not None:
        custom_global[_CHARGE_KEY] = float(explicit_charge)

    cell = Cell(
        lattice_vectors=np.asarray(lattice.matrix, dtype=np.float64),
        pbc=(True, True, True),
    )

    return CanonicalObject(
        frames=[
            Frame(
                index=0,
                atoms=AtomsBlock(symbols=symbols, positions=positions),
                cell=cell,
                dynamics=Dynamics(velocities=velocities),
                electronic=Electronic(charges=charges, magnetic_moments=magmoms),
            )
        ],
        provenance=_build_provenance(original_coordinate_system="fractional"),
        user_metadata=UserMetadata(custom_global=custom_global, custom_per_atom=custom_per_atom),
    )


def to_pymatgen(canonical: CanonicalObject) -> Structure:
    """Build a pymatgen ``Structure`` from a single-frame, periodic Canonical Object.

    The inverse of :func:`from_pymatgen` for the periodic case: carried ``pymatgen:<key>``
    payloads restore (oxidation states back onto the species, other namespaced keys back
    onto ``site_properties``, a carried total charge back via ``set_charge``). A
    trajectory refuses honestly — pymatgen holds a single structure, never a silent
    frame-0 slice; reduce with ``frame_selection`` first.
    """
    _require_pymatgen()
    from pymatgen.core import Lattice, Species, Structure

    if len(canonical.frames) != 1:
        raise ValueError(
            f"a pymatgen Structure/Molecule is a single structure; this object has "
            f"{len(canonical.frames)} frames — select one first (frame_selection)"
        )
    frame = canonical.frames[0]
    if frame.cell is None:
        raise NotImplementedError(
            "to_pymatgen: a lattice-less object becomes a pymatgen Molecule; "
            "Molecule support lands in S2"
        )
    um = canonical.user_metadata
    oxi_states = um.custom_per_atom.get(_OXI_STATE_KEY)
    sites: list[Species | str] = []
    for i, symbol in enumerate(frame.atoms.symbols):
        state = oxi_states[i] if oxi_states is not None else None
        sites.append(Species(symbol, state) if state is not None else symbol)

    structure = Structure(
        lattice=Lattice(frame.cell.lattice_vectors.tolist()),
        species=sites,
        coords=frame.atoms.positions.tolist(),
        coords_are_cartesian=True,
        site_properties=_restore_site_properties(frame, um),
    )
    carried_charge = um.custom_global.get(_CHARGE_KEY)
    if carried_charge is not None:
        if isinstance(carried_charge, bool) or not isinstance(carried_charge, (int, float)):
            raise ValueError(
                f"{_CHARGE_KEY} carry must be a number; got {type(carried_charge).__name__}"
            )
        structure.set_charge(float(carried_charge))
    return structure


def _restore_site_properties(frame: Frame, um: UserMetadata) -> dict[str, Any]:
    """Invert the S1 site-property/carry mapping: the three mapped arrays go back to their
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
        if key.startswith(_KEY_PREFIX):
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
