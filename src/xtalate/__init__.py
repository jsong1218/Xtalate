"""Xtalate — the trusted translation layer between computational chemistry file formats.

A converter that tells you exactly what it kept, what it lost, and why (MASTER_SPEC Part 0 §1).
The pure-Python library + CLI: format sniffing, an Information Discovery Engine, the
Capability-Matrix-driven Conversion Engine with explicit Recovery, and the automatic Validation
Engine — for XYZ, extXYZ, POSCAR, CONTCAR, XDATCAR, the ASE ``.traj`` format, and CIF.

v0.4 completes **Phase 1**: all seven formats read *and* write, and every pair among them
converts. It adds CIF — the only Phase 1 format that is fractional-native, states its cell as
parameters rather than vectors, and commonly carries an *asymmetric unit* that must be expanded
through the symmetry operations the file declares to be physically right. A file that names a
space group but declares no operations is refused rather than read as a partial structure, and
site occupancy is read into the first-class ``atoms.occupancies`` field (promoted from the earlier
namespaced carry-through at the v1.0 schema freeze). Pipeline memory remains sub-linear in frames
through the v0.3 frame-chunked streaming core. The Service (v0.5) exposes this core over HTTP under
``/v1``, and the Web UI (v0.6–v0.7) presents the whole upload → inspect → convert → recover → record
→ download
journey as a faithful, loss-first presentation layer — neither re-implementing any of it. v0.7
declares Parts 6–7 feature-complete (interactive recovery, the acknowledgment gate, the formats
explorer and history, the rendered docs site, and a first-class self-hosting deployment); the
plugin SDK and the ``/v1`` contract remain unfrozen until v1.0.
"""

__version__ = "0.7.0"
