"""The stress-carry key set — the ``custom_per_frame`` keys that carry an unresolved stress
tensor (MASTER_SPEC Part 4 §3.3; v1.2 M42-S5, DECISIONS.md D163).

The ``ambiguous_stress_convention`` recovery interprets a stress tensor a source parked in
``user_metadata.custom_per_frame`` because its sign convention is undeclared (D18: the
ASE-backed formats). Detection (conversion pre-flight), resolution (recovery engine), and the
RF-9 Assumption text all need to know *which* keys carry stress — a set that lives here, in the
SDK, the vocabulary layer below every consumer, so a future format adds its carry key in exactly
one place and every consumer sees it (the recovery and conversion layers do not import parsers).

Keyed by the carried key; valued by the source format's display name, which the Assumption text
renders as "Interpreted <name> stress as …" (RF-9).
"""

#: ``custom_per_frame`` key → display name of the format that owns the carry. The keys are
#: format-scoped per Part 2 §6.1 (``"<format>:<key>"``); the parsers/exporters also declare their
#: own ``_STRESS_KEY`` from the same spelling (D18), and this set is the cross-format collection.
STRESS_CARRY_KEYS: dict[str, str] = {
    "extxyz:stress": "extXYZ",
    "ase_traj:stress": "ASE `.traj`",
    # M55: ase_db is the third ASE-backed carry (D18 applied to `.db` rows — the sign
    # convention is unreconcilable without a source-declared choice, so stress rides in
    # custom_per_frame['ase_db:stress'] until the ambiguous_stress_convention recovery fires).
    "ase_db:stress": "ASE `.db`",
}
