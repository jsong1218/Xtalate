"""Recovery Engine — explicit, never-guessed handling of target-required-but-absent fields.

Implements the three-way hazard model and the fabricative bright line (Part 4 §3):
every applied recovery records an ``Assumption`` (and a ``supplied`` entry when it
fabricates); no default is ever applied silently. v0.1 scenarios: ``missing_lattice``
and ``frame_selection`` (preset-only). Populated in M5.
"""
