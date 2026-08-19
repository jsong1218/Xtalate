"""The image-flag carry key — the ``custom_per_atom`` key that carries a LAMMPS dump's
per-atom image flags (``ix``/``iy``/``iz``) as a structured payload (MASTER_SPEC Part 3 §4;
v1.3 M46-S3, DECISIONS.md D176).

A wrapped dump plus its image flags contains everything needed to reconstruct continuous
trajectories; dropping the flags makes unwrapping impossible while the output *looks* correct
— the version's sharpest silent-and-irreversible-loss hazard. The key lives here, the SDK
vocabulary layer below every consumer (the same home as the stress-carry keys, D163), so the
dump parser (which produces it), the capability declaration (which names it), and the
conversion pre-flight (which detects it and predicts the loss) all share one spelling — the
recovery and conversion layers do not import parsers.
"""

#: The ``custom_per_atom`` key the LAMMPS dump parser carries the per-atom image flags
#: (``ix``/``iy``/``iz``) under — a ``(N, 3)`` int array from frame 0 (the canonical per-atom
#: first-dim-N contract). Format-scoped per Part 2 §6.1 (``\"<format>:<key>\"``).
IMAGE_FLAGS_CARRY_KEY = "lammps_dump:image_flags"
