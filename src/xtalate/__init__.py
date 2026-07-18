"""Xtalate — the trusted translation layer between computational chemistry file formats.

A converter that tells you exactly what it kept, what it lost, and why (MASTER_SPEC Part 0 §1).
The pure-Python library + CLI: format sniffing, an Information Discovery Engine, the
Capability-Matrix-driven Conversion Engine with explicit Recovery, and the automatic Validation
Engine — for XYZ, extXYZ, POSCAR, CONTCAR, XDATCAR, and the ASE ``.traj`` format (six of the
seven Phase-1 formats; CIF is v0.4). v0.3 makes pipeline memory sub-linear in frames through a
frame-chunked streaming core, lands the two trajectory formats that need it, opens the plugin
surface to third-party formats discovered from Python entry points, and adds the benchmark corpus
and PR/nightly test-matrix split a scaling release needs. The Service (v0.5) and Web UI (v0.6)
build on this core without re-implementing any of it.
"""

__version__ = "0.3.0"
