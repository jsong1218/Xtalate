"""ASE database (``.db``) exporter (MASTER_SPEC Part 3 §3, Part 4 §1; v1.5 M55).

The mirror of ``parsers.ase_db``: it rebuilds a single ASE ``Atoms`` from the Canonical Object
and lets ``ase.db`` serialise it as one row of a SQLite database. Every mapping is the exact
inverse of the parser's, so ``.db → Canonical → .db' → Canonical'`` reproduces the scientific
content exactly (DECISIONS.md D18).

**One row, one structure.** A ``.db`` written on the single-file path holds exactly one
structure — the M55 model's load-bearing invariant (a dataset is aggregation, never a
trajectory; the rows-as-frames alternative breaks constant-N, Part 2 §3.2). So the exporter
refuses a multi-frame object rather than fanning it across rows: reduce the trajectory to one
frame via the Conversion Engine's ``frame_selection`` recovery first (the POSCAR/CIF
single-structure rule verbatim). Writing many rows from many *sources* is the batch **assemble**
seam (M55-S4), a different path that appends one contribution at a time.

The write mappings mirror ``exporters.ase_traj`` (the ASE-wrap write template), not
``exporters.extxyz``: charges/magnetic moments are written back to ASE's per-atom
``initial_charges`` / ``initial_magmoms`` arrays (the slots the parser reads them from), never to
the calculator, so they round-trip through the same seam they entered by. Energy and forces ride
on a ``SinglePointCalculator``; stress is dual-source exactly as ``ase_traj`` does it.

**Key–value / data restoration (the inverse of the parser's carry).** ``custom_global`` entries
under the ``ase_db:`` namespace are written back to the row: ``ase_db:data`` becomes the row's
arbitrary ``data`` blob and every other ``ase_db:<key>`` scalar becomes a ``key_value_pairs``
entry under its bare ``<key>`` (ASE rejects a ``:`` in a key, which is exactly why the namespace
is stripped). A ``custom_global`` entry from another format's namespace cannot be spelled as an
ASE key and is the Conversion Engine's to report as ``removed`` — this exporter writes only what
``.db`` can express (Part 4 §1), which the ``user_metadata.custom_global`` capability declares as
a ``writable_custom_key_pattern`` restricted to the ``ase_db:`` namespace (D69).

``ase.db`` opens a database only by real path, so — like the parser — the write goes to a
temporary ``.db`` file whose bytes are then copied into the caller's stream.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
from ase import Atoms
from ase import units as ase_units
from ase.calculators.singlepoint import SinglePointCalculator
from ase.constraints import FixAtoms
from ase.db import connect
from ase.stress import full_3x3_to_voigt_6_stress, voigt_6_to_full_3x3_stress

from xtalate.schema import CanonicalObject, Frame
from xtalate.sdk import (
    AssembleContribution,
    CapabilityLevel,
    ExporterPlugin,
    ExporterWarning,
    FieldCapability,
    FormatCapabilities,
)

FORMAT_ID = "ase_db"
_KEY_PREFIX = "ase_db:"
_STRESS_KEY = "ase_db:stress"
_DATA_KEY = "ase_db:data"
# custom_global keys this exporter can spell back into a row: only its own ``ase_db:`` namespace,
# and the segment after it carries no further colon (ASE keys forbid ':', so the parser only ever
# carries single-segment names — ``ase_db:label``, ``ase_db:data``). A foreign-namespace key such
# as ``poscar:comment`` fails the fullmatch and is reported ``removed``, never entered into the
# write plan and then silently dropped (D69; the extXYZ per-atom precedent).
_WRITABLE_CUSTOM_GLOBAL_PATTERN = rf"{_KEY_PREFIX}[^:]*"
# (Å/fs) per one ASE internal velocity unit — i.e. ase_units.fs. Canonical Å/fs *divided by* this
# yields ASE units (the exact inverse of the parser's multiply). Defined here, not imported, so the
# exporter layer does not depend on the parser layer (P2; mirrors exporters.ase_traj).
_ANG_PER_FS_PER_ASE_VEL = ase_units.fs
# Scalars ASE accepts as a key_value_pairs value (bool is an int subclass, hence listed explicitly
# for intent; ASE stores it as an int). Anything else in custom_global is not a kv value.
_KV_SCALARS = (str, bool, int, float)


class AseDbExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "ASE Database"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        atoms, key_value_pairs, data = self._row_from(canonical)
        # ase.db opens a database only by real path, so write to a temp .db and copy its bytes into
        # the caller's stream (the parser spools the same way for the same reason).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.db"
            db = connect(path, use_lock_file=False)
            db.write(atoms, key_value_pairs=key_value_pairs, data=data or None)
            stream.write(path.read_bytes())

    def assemble(self, contributions: list[AssembleContribution], stream: BinaryIO) -> None:
        """Combine N per-source conversions into **one** multi-row ASE ``.db`` dataset (M55-S4).

        A ``.db`` is a SQLite database of independent rows, so — unlike extXYZ — its per-source
        outputs cannot be byte-concatenated; the assemble rebuilds each row from the contribution's
        own write-plan-filtered Canonical Object (the object the engine exported and already
        validated on the ordinary path), appending them into one database in manifest/fan-out
        order. Each contribution is a single-structure object (a per-source or fanned per-row
        conversion — a ``.db`` exporter refuses a multi-frame object, so every contribution is one
        row), written exactly as ``export`` writes the single-file row, so a row in the assembled
        dataset is content-identical to the same source converted alone (SQLite rows are
        independent; per-contribution validation keeps its meaning). ``ase.db`` opens a database
        only by real path, so the N rows go to one temp ``.db`` whose bytes are copied out."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.db"
            db = connect(path, use_lock_file=False)
            for contribution in contributions:
                atoms, key_value_pairs, data = self._row_from(contribution.canonical)
                db.write(atoms, key_value_pairs=key_value_pairs, data=data or None)
            stream.write(path.read_bytes())

    def _row_from(self, canonical: CanonicalObject) -> tuple[Atoms, dict[str, Any], dict[str, Any]]:
        """Build one ``.db`` row — the ASE ``Atoms`` plus its ``key_value_pairs`` and ``data`` blob
        — from a single-structure Canonical Object. Shared by the single-file ``export`` and the
        batch ``assemble`` (one row per contribution) so the two paths write a row identically. A
        multi-frame object is refused: a ``.db`` written on either path holds one structure per row
        (a dataset is aggregation, never a trajectory; Part 2 §3.2)."""
        if len(canonical.frames) != 1:
            raise ValueError(
                "an ASE database written on the single-file path holds one structure; reduce the "
                "trajectory to one frame via the Conversion Engine's frame_selection recovery "
                "before export, or write every structure as its own row under --batch assemble "
                "(Part 4 §3; M55)"
            )
        frame = canonical.frames[0]
        # The one frame's per-frame carry row (only ase_db:stress lives here), resolved the same
        # way ase_traj resolves it — from custom_per_frame indexed by the frame's position.
        per_frame = canonical.user_metadata.custom_per_frame
        per_frame_custom = {
            key: (values[frame.index] if frame.index < len(values) else None)
            for key, values in per_frame.items()
        }
        atoms = self._atoms_from(frame, per_frame_custom)
        key_value_pairs, data = self._row_metadata(canonical)
        return atoms, key_value_pairs, data

    def _atoms_from(self, frame: Frame, per_frame_custom: dict[str, Any]) -> Atoms:
        """Rebuild one ASE ``Atoms`` from a canonical frame plus this frame's per-frame carry — the
        exact inverse of the parser's row read. Charges/moments go to the per-atom ``initial_*``
        arrays (the parser's source), energy/forces/stress to a ``SinglePointCalculator``."""
        atoms = Atoms(
            symbols=list(frame.atoms.symbols),
            positions=np.asarray(frame.atoms.positions, dtype=float),
        )
        if frame.atoms.masses is not None:
            atoms.set_masses(np.asarray(frame.atoms.masses, dtype=float))
        if frame.cell is not None:
            atoms.set_cell(np.asarray(frame.cell.lattice_vectors, dtype=float))
            atoms.set_pbc(frame.cell.pbc)
        if frame.dynamics.velocities is not None:
            v_ase = np.asarray(frame.dynamics.velocities, dtype=float) / _ANG_PER_FS_PER_ASE_VEL
            atoms.set_velocities(v_ase)
        # electronic.charges/magmoms round-trip through ASE's per-atom initial_* arrays (the parser
        # reads them from there); the exporter writes them back to the same place — the ase_traj
        # rule, not extXYZ's calculator routing.
        if frame.electronic.charges is not None:
            atoms.set_initial_charges(np.asarray(frame.electronic.charges, dtype=float))
        if frame.electronic.magnetic_moments is not None:
            atoms.set_initial_magnetic_moments(
                np.asarray(frame.electronic.magnetic_moments, dtype=float)
            )
        self._apply_constraints(atoms, frame)

        # Stress (Part 2 §3.7.1, D163): dual-source, mirroring ase_traj's M42-S5 write side. A
        # resolved `electronic.stress` is written from the field, reversing the canonical
        # tension-positive normalization to the exporter's declared target convention — ASE
        # compression-positive, `stress_output_convention="ase_sign_convention"` — and reported
        # by `export_warnings`, never silently. An unresolved object falls back to the verbatim
        # `ase_db:stress` carry so an opaque .db→.db pass-through round-trips the numbers exactly.
        stress = None
        if frame.electronic.stress is not None:
            # Negate to ASE's compression-positive convention, then compress to Voigt-6 — ASE's
            # native stress representation, which a .db round-trips as a (6,) vector. A full 3x3 is
            # flattened to (9,) by the SQLite schema on read and would not reshape back to a tensor,
            # so writing Voigt-6 is what keeps the carry comparable. Validation reverses the (6,)
            # carry to a (3,3) tension-positive tensor via the declared stress_output_convention.
            stress = full_3x3_to_voigt_6_stress(-np.asarray(frame.electronic.stress, dtype=float))
        else:
            carried = per_frame_custom.get(_STRESS_KEY)
            if carried is not None:
                stress = np.asarray(carried, dtype=float)

        results: dict[str, Any] = {}
        if frame.electronic.total_energy is not None:
            results["energy"] = float(frame.electronic.total_energy)
        if frame.dynamics.forces is not None:
            results["forces"] = np.asarray(frame.dynamics.forces, dtype=float)
        if stress is not None:
            results["stress"] = stress
        if results:
            atoms.calc = SinglePointCalculator(atoms, **results)
        return atoms

    @staticmethod
    def _apply_constraints(atoms: Atoms, frame: Frame) -> None:
        """Write ``fixed_atoms`` constraints back as ASE ``FixAtoms`` (the ase_traj rule): an
        empty/``None`` list leaves ASE's default (no constraint); an unrepresentable kind is the
        Conversion Engine's to report as ``removed``."""
        constraints = frame.dynamics.constraints
        if not constraints:
            return
        fixed: list[int] = []
        for con in constraints:
            if con.kind == "fixed_atoms":
                fixed.extend(int(i) for i in con.atom_indices)
        if fixed:
            atoms.set_constraint(FixAtoms(indices=sorted(set(fixed))))

    def _row_metadata(self, canonical: CanonicalObject) -> tuple[dict[str, Any], dict[str, Any]]:
        """Invert the parser's key–value / data carry. ``ase_db:data`` → the row's ``data`` blob;
        every other ``ase_db:<key>`` scalar → a ``key_value_pairs`` entry under the bare ``<key>``.
        A drop *by name* (a foreign-namespace key) is reported ``removed`` by the Conversion
        Engine's key-pattern pre-flight. A drop *by value type* (a non-dict ``ase_db:data``, a
        non-scalar ``ase_db:<key>``) cannot be an ASE key/value and is skipped here — but never
        silently: ``export_warnings`` reports each such drop (ASEDB-5, review R5), so the write
        report is honest (P5)."""
        custom_global = canonical.user_metadata.custom_global
        key_value_pairs: dict[str, Any] = {}
        data: dict[str, Any] = {}
        for key, value in custom_global.items():
            if not key.startswith(_KEY_PREFIX):
                continue  # a colon-bearing foreign key is not a valid ASE key; reported removed
            if _value_drop_reason(key, value) is not None:
                continue  # dropped by value type; export_warnings reports it (ASEDB-5)
            if key == _DATA_KEY:
                assert isinstance(value, dict)  # _value_drop_reason guaranteed it for ase_db:data
                data = dict(value)
                continue
            key_value_pairs[key[len(_KEY_PREFIX) :]] = value
        return key_value_pairs, data

    # -- capabilities ------------------------------------------------------------------

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        partial = CapabilityLevel.PARTIAL
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "atoms.masses": FieldCapability(level=partial, notes="Written as a masses array."),
                "cell.lattice_vectors": FieldCapability(
                    level=partial, notes="Written when a cell is present."
                ),
                "cell.pbc": FieldCapability(level=partial, notes="Written alongside the cell."),
                "dynamics.velocities": FieldCapability(
                    level=partial, notes="Written as momenta; unit-converted."
                ),
                "dynamics.forces": FieldCapability(
                    level=partial, notes="Written on the calculator."
                ),
                "dynamics.constraints": FieldCapability(
                    level=partial, notes="Only fixed_atoms (→ ASE FixAtoms); other kinds dropped."
                ),
                "electronic.total_energy": FieldCapability(
                    level=partial, notes="Written on the calculator."
                ),
                "electronic.charges": FieldCapability(
                    level=partial, notes="Written as the initial_charges array."
                ),
                "electronic.magnetic_moments": FieldCapability(
                    level=partial, notes="Written as the initial_magmoms array."
                ),
                "electronic.stress": FieldCapability(
                    level=partial,
                    notes="Written only when the stress sign convention is resolved via the "
                    "ambiguous_stress_convention recovery: from electronic.stress, sign-reversed "
                    "to the compression-positive convention ASE-native databases carry "
                    "(STRESS_SIGN_CONVENTION_CHANGED warning). An unresolved object's "
                    "ase_db:stress carry is written verbatim.",
                ),
                "user_metadata.custom_global": FieldCapability(
                    level=partial,
                    notes="ase_db:<key> scalars restore as key_value_pairs and ase_db:data as the "
                    "row's data blob; a foreign-namespace or non-scalar entry cannot be an ASE "
                    "key/value and is reported removed.",
                ),
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only the ase_db:stress carry survives (written as the row's calculator "
                    "stress, re-parsed back under its own name); other per-frame customs have no "
                    "ASE row slot — a .db persists key_value_pairs and data, never atoms.info.",
                ),
            },
            # A row's key-value / data store is open-ended, but ASE forbids ':' in a key, so the
            # custom_global writable set is a name *pattern* (D69, the extXYZ precedent): only
            # ``ase_db:<name>`` keys survive write → re-parse under their own spelling. A
            # foreign-namespace key is classified `removed` in pre-flight rather than
            # promised-and-dropped, so `canonical′` matches what the exporter actually writes.
            writable_custom_key_pattern={
                "user_metadata.custom_global": _WRITABLE_CUSTOM_GLOBAL_PATTERN
            },
            # custom_per_frame holds exactly one writable key: the ``ase_db:stress`` carry, which
            # rides the row's calculator stress. Nothing else per-frame has a row slot (unlike
            # ase_traj, a .db does not persist atoms.info), so a fixed list — not a pattern —
            # states the honest set; every other per-frame key is `removed`.
            writable_custom_keys={"user_metadata.custom_per_frame": [_STRESS_KEY]},
            max_frames=1,  # one row → one structure (a trajectory needs frame_selection first)
            # N single-structure sources combine into one multi-row dataset by appending one row
            # per contribution (M55-S4 batch assemble seam; DECISIONS.md D208). Orthogonal to
            # max_frames=1: each row is one structure, the container holds N of them.
            assemble_capable=True,
            required_fields=["atoms.symbols", "atoms.positions"],
            allows_open_boundaries=True,  # ASE writes pbc; an open cell is expressible.
            representable_constraint_kinds=["fixed_atoms"],
            native_coordinate_system="cartesian",
            lossy_notes=[],
            # The stress this exporter writes is in ASE's compression-positive convention — the
            # inverse of the canonical tension-positive (Part 2 §3.7.1) — so the Validation Engine
            # can compare a re-parsed carry back in canonical space (D151, D163).
            stress_output_convention="ase_sign_convention",
        )

    def export_warnings(self, canonical: CanonicalObject) -> list[ExporterWarning]:
        """Report the stress transformations this exporter applies on write (Part 2 §3.7.1,
        D163), mirroring ase_traj's M42-S5 write side. Two warnings, each firing only when its
        trigger is present:

        * ``STRESS_SIGN_CONVENTION_CHANGED`` — a populated ``electronic.stress`` is reversed from
          the canonical tension-positive convention to the compression-positive convention
          ASE-native databases carry (never silent).
        * ``STRESS_CARRY_DROPPED`` — the frame carries **both** a populated ``electronic.stress``
          and a *differing* ``ase_db:stress`` carry; the field wins and the carry's numbers are
          dropped. Fires only when the dropped numbers actually differ from what was written.

        An unresolved object (only the legacy carry, no populated field) is written verbatim and
        warrants neither warning."""
        warnings: list[ExporterWarning] = []
        populated = [f.index for f in canonical.frames if f.electronic.stress is not None]
        if populated:
            frames_desc = f"frame(s) {populated}" if len(populated) > 1 else f"frame {populated[0]}"
            warnings.append(
                ExporterWarning(
                    code="STRESS_SIGN_CONVENTION_CHANGED",
                    message=(
                        "stress reversed from the canonical tension-positive convention to the "
                        "compression-positive convention ASE-native databases carry "
                        f"({frames_desc}); the output's stress tensor has the opposite sign of "
                        "the canonical value"
                    ),
                )
            )
        carry_values = canonical.user_metadata.custom_per_frame.get(_STRESS_KEY)
        dropped: list[int] = []
        if carry_values is not None:
            for frame in canonical.frames:
                if frame.electronic.stress is None or frame.index >= len(carry_values):
                    continue
                carried = carry_values[frame.index]
                if carried is None:
                    continue
                written = -np.asarray(frame.electronic.stress, dtype=float)
                carried_arr = np.asarray(carried, dtype=float)
                # Only the two shapes the ASE-backed formats write are comparable (Voigt-6 or
                # full 3×3). ASE itself can flatten a full 3×3 calculator stress to a bare
                # length-9 array on .db write; that value cannot be judged against the written
                # tensor — skip the drop-check rather than broadcast-crash (ASEDB-1, review
                # R4): the field is still written, the unrecognized carry is simply not
                # compared.
                if carried_arr.shape in {(6,), (3, 3)}:
                    if carried_arr.shape == (6,):
                        carried_arr = np.asarray(
                            voigt_6_to_full_3x3_stress(carried_arr), dtype=float
                        )
                    if not np.allclose(carried_arr, written):
                        dropped.append(frame.index)
        if dropped:
            frames_desc = f"frame(s) {dropped}" if len(dropped) > 1 else f"frame {dropped[0]}"
            warnings.append(
                ExporterWarning(
                    code="STRESS_CARRY_DROPPED",
                    message=(
                        f"a populated electronic.stress coexisted with a differing "
                        f"'ase_db:stress' carry on {frames_desc}; the field was written and the "
                        "carry's numbers were dropped"
                    ),
                )
            )

        # ASEDB-5 (review R5): a custom_global key that matches the writable namespace *by name*
        # but holds a value type ASE cannot store — a non-scalar ``ase_db:<key>``, a non-dict
        # ``ase_db:data`` — is dropped on write. The pre-flight predicts it preserved by name, so
        # this audit is what keeps the write report honest (P5): the value-type exclusion the name
        # pattern cannot see is surfaced here, never left as a silent skip.
        for key, value in canonical.user_metadata.custom_global.items():
            reason = _value_drop_reason(key, value)
            if reason is not None:
                warnings.append(
                    ExporterWarning(
                        code="ASE_DB_KV_VALUE_DROPPED",
                        message=(
                            f"custom_global entry {key!r} matches the writable ase_db namespace "
                            f"but its value cannot be stored as an ASE row key/value or data blob "
                            f"and was not written: {reason}"
                        ),
                    )
                )
        return warnings


def _value_drop_reason(key: str, value: Any) -> str | None:
    """Why an ``ase_db``-namespaced ``custom_global`` entry is dropped *by value type* on write,
    or ``None`` if it can be written. ``ase_db:data`` needs a ``dict``; an ``ase_db:<key>`` needs a
    scalar (``_KV_SCALARS``, the values ASE persists as key_value_pairs). Shared by the write path
    (``_row_metadata``) and ``export_warnings`` so the two can never drift on what is silently
    dropped (ASEDB-5, review R5). A foreign-namespace key returns ``None``: it is dropped by name
    and reported ``removed`` by the pre-flight key pattern, not by this value audit."""
    if not key.startswith(_KEY_PREFIX):
        return None
    if key == _DATA_KEY:
        if isinstance(value, dict):
            return None
        return (
            f"the '{_DATA_KEY}' data blob must be a JSON object (dict) to be stored as the row's "
            "data blob; a non-dict value cannot be written"
        )
    if isinstance(value, _KV_SCALARS):
        return None
    return (
        f"an 'ase_db:<key>' value must be a scalar (str/bool/int/float), but "
        f"'{key[len(_KEY_PREFIX) :]}' holds a {type(value).__name__}; ASE cannot store it as a "
        "key_value_pairs entry"
    )


def make_ase_db_exporter() -> AseDbExporter:
    return AseDbExporter()
