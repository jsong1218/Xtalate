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
site occupancy is carried under a namespaced key rather than modelled, since the Canonical Model
has no occupancy field. Pipeline memory remains sub-linear in frames through the v0.3
frame-chunked streaming core. The Service (v0.5) and Web UI (v0.6) build on this core without
re-implementing any of it.
"""

__version__ = "0.4.0"
