"""In-memory adapters between scientific-Python objects and the Canonical Object.

These are **library-user seams, not registered formats** (v1.5 M57; DECISIONS.md D215):
there is no file, so there is no sniffer entry, no capability-matrix row, no CLI
subcommand, no ``ConversionReport``, and no entry in ``docs/vocabulary.json`` — the
format machinery is deliberately not involved. Users compose Xtalate with pymatgen in
one process and call these functions directly:

    from xtalate.adapters import from_pymatgen, to_pymatgen

pymatgen is an **optional extra** (``xtalate[pymatgen]``) *consumed* at this seam,
never a dependency (D4): it is imported lazily inside the function bodies, so both
``import xtalate`` and ``import xtalate.adapters`` succeed with pymatgen absent.
"""

from xtalate.adapters.pymatgen import from_pymatgen, to_pymatgen

__all__ = ["from_pymatgen", "to_pymatgen"]
