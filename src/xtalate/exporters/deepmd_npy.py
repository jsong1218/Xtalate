"""DeePMD-kit NumPy system-directory exporter."""

from __future__ import annotations

from collections import OrderedDict
from io import BytesIO
from typing import BinaryIO

import numpy as np

from xtalate.schema import CanonicalObject
from xtalate.sdk import (
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
        output[TYPE_FILE] = (
            " ".join(str(symbols.index(symbol)) for symbol in symbols) + "\n"
        ).encode()
        output[TYPE_MAP_FILE] = (" ".join(dict.fromkeys(symbols)) + "\n").encode()
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
            },
            required_fields=["atoms.symbols", "atoms.positions"],
            directory_format=True,
            native_coordinate_system="cartesian",
        )


def _npy(value: np.ndarray) -> bytes:
    stream = BytesIO()
    np.save(stream, value, allow_pickle=False)
    return stream.getvalue()


def make_deepmd_npy_exporter() -> DeepmdNpyExporter:
    return DeepmdNpyExporter()
