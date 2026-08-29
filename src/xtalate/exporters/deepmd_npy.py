"""DeePMD-kit NumPy system-directory exporter."""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
from typing import BinaryIO

import numpy as np

from xtalate.schema import CanonicalObject
from xtalate.sdk import (
    AssembleContribution,
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
)
from xtalate.sdk.deepmd import (
    BOX_FILE,
    COORD_FILE,
    ENERGY_FILE,
    FORCE_FILE,
    FORMAT_ID,
    TYPE_FILE,
    TYPE_MAP_FILE,
    VIRIAL_FILE,
    virial_from_stress,
)


class DeepmdNpyExporter(ExporterPlugin):
    format_id = FORMAT_ID
    format_name = "DeePMD-kit NumPy system"
    version = "0.1.0"

    def export(self, canonical: CanonicalObject, stream: BinaryIO) -> None:
        raise NotImplementedError("deepmd_npy is a directory format; use export_dir()")

    def unrepresentable(self, canonical: CanonicalObject) -> str | None:
        """Why this object cannot be written as one DeePMD system, or ``None`` (D179).

        A DeePMD system is fixed-composition **and** fixed-order — ``type.raw`` is a single
        per-atom type array shared by every frame (Part 2 §3.2). A trajectory whose per-atom
        symbol sequence changes across frames (a substitution/alchemical run — schema-legal at a
        constant atom *count*) has no such array, so it is refused **cleanly**
        (``UNREPRESENTABLE_VALUE``, a completed refused report) rather than crashing mid-write in
        ``export_dir``. Reordering or splitting atoms to force a fit would silently permute the
        structure, which Xtalate never does (identity ``atom_permutation``, D43). A frame that
        pairs a stress with a degenerate (zero-volume) cell is refused the same way: writing that
        stress as a virial requires multiplying by the cell volume, so ``virial_from_stress``
        would crash mid-write on volume ≤ 0 — the honest outcome is this refusal, not a crash
        (and Xtalate will not fabricate a volume to force a fit). The engine calls this once on
        the write-plan-filtered object, ahead of ``export_dir``.
        """
        if not canonical.frames:
            return "DeePMD requires at least one frame; the write plan left an empty system."
        symbols = list(canonical.frames[0].atoms.symbols)
        if any(list(frame.atoms.symbols) != symbols for frame in canonical.frames):
            return (
                "DeePMD stores one fixed per-atom type array (type.raw) for the whole system, but "
                "this trajectory's atom composition or order changes across frames. Xtalate will "
                "not silently reorder or split atoms to force a fit."
            )
        for index, frame in enumerate(canonical.frames):
            if frame.electronic.stress is None or frame.cell is None:
                continue
            lattice = np.asarray(frame.cell.lattice_vectors, dtype=np.float64)
            if np.abs(np.linalg.det(lattice)) <= 0:
                return (
                    f"DeePMD writes stress as virial = -stress·volume, which requires a non-zero "
                    f"cell volume, but frame {index} has a stress paired with a degenerate "
                    "(zero-volume) lattice. Xtalate will not fabricate a volume to force a fit."
                )
        return None

    def export_dir(self, canonical: CanonicalObject) -> dict[str, bytes]:
        if not canonical.frames:
            raise ValueError("cannot export an empty DeePMD system")
        first = canonical.frames[0]
        symbols = list(first.atoms.symbols)
        if any(list(frame.atoms.symbols) != symbols for frame in canonical.frames):
            raise ValueError("DeePMD requires fixed composition and atom order")
        n_frames = len(canonical.frames)
        coords = np.asarray([frame.atoms.positions for frame in canonical.frames], dtype=np.float64)
        boxes = np.zeros((n_frames, 9), dtype=np.float64)
        for index, frame in enumerate(canonical.frames):
            if frame.cell is not None:
                boxes[index] = np.asarray(frame.cell.lattice_vectors, dtype=np.float64).reshape(9)
        output: OrderedDict[str, bytes] = OrderedDict()
        type_raw, type_map_raw = _type_files(canonical)
        output[TYPE_FILE] = type_raw
        output[TYPE_MAP_FILE] = type_map_raw
        output["set.000/" + COORD_FILE] = _npy(coords.reshape((n_frames, -1)))
        output["set.000/" + BOX_FILE] = _npy(boxes)
        energies = [frame.electronic.total_energy for frame in canonical.frames]
        if all(value is not None for value in energies):
            output["set.000/" + ENERGY_FILE] = _npy(np.asarray(energies, dtype=np.float64))
        forces = [frame.dynamics.forces for frame in canonical.frames]
        if all(value is not None for value in forces):
            output["set.000/" + FORCE_FILE] = _npy(
                np.asarray([value for value in forces], dtype=np.float64).reshape((n_frames, -1))
            )
        stresses = [frame.electronic.stress for frame in canonical.frames]
        if all(value is not None for value in stresses) and all(
            frame.cell is not None for frame in canonical.frames
        ):
            output["set.000/" + VIRIAL_FILE] = _npy(
                virial_from_stress(
                    np.asarray([value for value in stresses], dtype=np.float64), boxes
                )
            )
        return dict(output)

    def assemble_dir(
        self, contributions: list[AssembleContribution]
    ) -> tuple[dict[str, bytes], list[str]]:
        """Group contributions by composition into one system directory per group.

        Returns ``(output, systems)`` — the written files and the per-contribution ``system_NNN``
        assignment, **index-aligned with ``contributions``** (the ordered source→system mapping
        the batch aggregate records; the batch layer names the sources it handed over, M56-S3 /
        D214/D227). The group key is the exact per-atom symbol sequence of a contribution's frames
        (a DeePMD system is fixed-composition **and** fixed-order — ``type.raw`` is a per-atom
        array), so contributions whose atoms are ordered differently are separate systems rather
        than a silent reorder (identity ``atom_permutation``; Xtalate never reorders).
        Deterministic by first appearance; the grouping is named in the batch aggregate note
        (D214).
        """
        groups: OrderedDict[tuple[str, ...], list[tuple[int, AssembleContribution]]] = OrderedDict()
        for position, contribution in enumerate(contributions):
            symbols = tuple(contribution.canonical.frames[0].atoms.symbols)
            groups.setdefault(symbols, []).append((position, contribution))
        output: dict[str, bytes] = {}
        systems: list[str] = [""] * len(contributions)
        for index, group in enumerate(groups.values()):
            prefix = f"system_{index:03d}/"
            merged = [contribution for _, contribution in group]
            for path, content in self._merge_group(merged).items():
                output[prefix + path] = content
            # Position-mapped, not regrouped: ``systems[i]`` names the system of
            # ``contributions[i]`` (members of one group are *not* contiguous in the input).
            for position, _ in group:
                systems[position] = prefix.removesuffix("/")
        return output, systems

    def _merge_group(self, contributions: list[AssembleContribution]) -> dict[str, bytes]:
        frames = []
        for contribution in contributions:
            frames.extend(contribution.canonical.frames)
        merged = contributions[0].canonical.model_copy(update={"frames": frames})
        return self.export_dir(merged)

    def capabilities(self) -> FormatCapabilities:
        partial = FieldCapability(level=CapabilityLevel.PARTIAL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="write",
            fields={
                "atoms.symbols": partial,
                "atoms.positions": FieldCapability(level=CapabilityLevel.FULL),
                "cell.lattice_vectors": partial,
                "cell.pbc": partial,
                "dynamics.forces": partial,
                "electronic.total_energy": partial,
                "electronic.stress": partial,
                "user_metadata.custom_global": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes=(
                        "deepmd_npy:type_map / deepmd_npy:type_indices restore through "
                        "type_map.raw / type.raw (the carried numbering); a foreign-namespace "
                        "key cannot be spelled in the fixed layout and is reported removed."
                    ),
                ),
            },
            required_fields=["atoms.symbols", "atoms.positions"],
            directory_format=True,
            assemble_capable=True,
            # A parsed DeePMD system carries its source numbering under ``deepmd_npy:*`` and the
            # exporter restores it through ``type.raw``/``type_map.raw`` (D209's carry, written
            # back); the pattern declares that restore so pre-flight keeps the keys rather than
            # promising-and-dropping them (D69, the ase_db precedent).
            writable_custom_key_pattern={"user_metadata.custom_global": "deepmd_npy:[^:]*"},
            native_coordinate_system="cartesian",
        )


def _type_files(canonical: CanonicalObject) -> tuple[bytes, bytes]:
    """The ``type.raw`` / ``type_map.raw`` bytes for a system.

    A system parsed from a DeePMD directory carries its source numbering verbatim under
    ``deepmd_npy:type_map`` + ``deepmd_npy:type_indices`` (D209); restoring both writes that
    numbering back byte-faithfully — the only faithful inverse of the parser's carry (P1). A
    foreign object (e.g. extXYZ → deepmd_npy) has no carry, so the numbering is derived from the
    species list in first-appearance order — the ordinary ``type_map.raw`` → symbols →
    ``type.raw`` derivation.
    """
    global_custom = canonical.user_metadata.custom_global
    carried_map = global_custom.get("deepmd_npy:type_map")
    carried_indices = global_custom.get("deepmd_npy:type_indices")
    if (
        isinstance(carried_map, list)
        and carried_map
        and isinstance(carried_indices, list)
        and all(isinstance(index, int) for index in carried_indices)
    ):
        return (
            (" ".join(str(index) for index in carried_indices) + "\n").encode("utf-8"),
            (" ".join(str(token) for token in carried_map) + "\n").encode("utf-8"),
        )
    symbols = list(canonical.frames[0].atoms.symbols)
    unique = list(dict.fromkeys(symbols))
    index_of = {symbol: index for index, symbol in enumerate(unique)}
    return (
        (" ".join(str(index_of[symbol]) for symbol in symbols) + "\n").encode(),
        (" ".join(unique) + "\n").encode(),
    )


def _npy(value: np.ndarray) -> bytes:
    stream = BytesIO()
    np.save(stream, value, allow_pickle=False)
    return stream.getvalue()


def make_deepmd_npy_exporter() -> DeepmdNpyExporter:
    return DeepmdNpyExporter()
