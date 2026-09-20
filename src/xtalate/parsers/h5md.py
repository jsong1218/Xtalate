"""H5MD (HDF5-for-molecular-data) parser (MASTER_SPEC Part 3 §3; v2.0 M74).

Reads one H5MD file — the community HDF5 layout for molecular data — into a Canonical Object via
``h5py``. H5MD is the eighth first-party format and the one that proves the M72/M73 variable-N
engines against a real binary container: a trajectory whose atom count differs per frame is read
natively, each frame carrying its own N (P3), never coerced to a constant-N shape.

**Streaming-first.** ``parse`` is defined as ``materialize(parse_stream(...))`` (as XDATCAR and ASE
traj), so the whole-file and streamed readings are one code path that cannot diverge (D56). ``h5py``
gives random access into the file, so ``parse_stream`` genuinely yields one frame at a time and peak
memory tracks the resident frame, not the frame count.

**The variable-N read mechanism (paired with the exporter, DECISIONS.md D-DEP).** A time-dependent
element is a ``{step, time, value}`` triple. When ``value`` is a per-step variable-length (VLEN)
array — the layout ``exporters.h5md`` writes — each entry is that frame's data with its own particle
dimension, so N is read per frame. A constant-N ``[T, N, D]`` ``value`` is the S2 generalization;
S1 pins the VLEN round-trip.

Like every wrapped-container parser, absent optional groups launder to absence, never to zeros or
defaults (P3); H5MD's ``unit`` attributes are honored when present and their absence recorded rather
than assumed (S2).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, BinaryIO

import h5py
import numpy as np

from xtalate import __version__
from xtalate.parsers._common import build_provenance
from xtalate.schema import (
    SCHEMA_VERSION,
    AtomsBlock,
    Cell,
    Frame,
    TrajectoryMetadata,
)
from xtalate.schema.elements import symbol_for
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    FrameStream,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
    StreamFrame,
    StreamHeader,
    materialize,
)

if TYPE_CHECKING:
    pass

FORMAT_ID = "h5md"
# HDF5 files begin with this 8-byte signature (see the HDF5 spec); used only for sniffing.
_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
_PARSER_VERSION = f"{FORMAT_ID}-parser {__version__} (h5py {h5py.__version__})"


def _error(code: str, message: str, *, location: str | None = None) -> ParseError:
    return ParseError([ParseIssue(severity="error", code=code, message=message, location=location)])


class H5MDParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "H5MD"
    version = "0.1.0"
    file_extensions = (".h5", ".h5md", ".hdf5")

    def sniff(self, head: bytes, filename: str | None) -> float:
        # HDF5 is a binary container with a fixed magic; H5MD is one layout within it. The magic
        # alone cannot distinguish H5MD from any other HDF5 file, so it is a weak hint here (S2
        # opens the head to probe for /h5md + /particles); the extension is weaker still.
        if head.startswith(_HDF5_MAGIC):
            return 0.4
        if filename is not None and filename.endswith((".h5md", ".h5", ".hdf5")):
            return 0.2
        return 0.0

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        """Whole-file read, defined as the streamed read drained into an object (D56)."""
        frame_stream = self.parse_stream(stream, filename=filename)
        canonical, issues = materialize(frame_stream)
        return ParseResult(canonical=canonical, issues=issues)

    def supports_streaming(self) -> bool:
        return True

    def parse_stream(self, stream: BinaryIO, *, filename: str | None) -> FrameStream:
        try:
            f = h5py.File(stream, "r")
        except Exception as exc:  # h5py raises OSError family; normalise to the contract
            raise _error(
                "H5MD_MALFORMED_STRUCTURE", f"could not open the file as HDF5: {exc}"
            ) from exc

        group = self._single_particle_group(f)
        positions = group["position"]["value"]
        species = group["species"]["value"]
        n_steps = positions.shape[0]
        box_cell = self._read_box(group)

        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=[
                f"read via h5py {h5py.__version__}; H5MD per-step variable-length elements read "
                "with each frame's own atom count (P3)."
            ],
            parser_version=_PARSER_VERSION,
        )
        header = StreamHeader(
            schema_version=SCHEMA_VERSION,
            provenance=provenance,
            trajectory=TrajectoryMetadata(timestep=None),
        )

        def _frames() -> Iterator[StreamFrame]:
            try:
                for index in range(n_steps):
                    atomic_numbers = np.asarray(species[index]).reshape(-1)
                    symbols = [symbol_for(int(z)) for z in atomic_numbers]
                    pos = np.asarray(positions[index], dtype=np.float64).reshape(-1, 3)
                    frame = Frame(
                        index=index,
                        atoms=AtomsBlock(symbols=symbols, positions=pos),
                        cell=box_cell,
                    )
                    yield StreamFrame(frame=frame)
            finally:
                f.close()

        return FrameStream(header, _frames())

    @staticmethod
    def _single_particle_group(f: h5py.File) -> h5py.Group:
        """Return the one ``/particles/<grp>`` group, or refuse. S1 handles the well-formed
        single-group case; S2 adds the multi-group refusal and the missing-group error codes."""
        particles = f.get("particles")
        if particles is None:
            raise _error(
                "H5MD_MISSING_REQUIRED_GROUP",
                "file has no /particles group (not an H5MD trajectory)",
            )
        names = list(particles.keys())
        return particles[names[0]]

    @staticmethod
    def _read_box(group: h5py.Group) -> Cell | None:
        """Read a fixed-in-time ``box/edges`` (a dataset directly) into a Cell, with pbc from
        ``box/boundary``. Absent box → no cell (absence, P3)."""
        box = group.get("box")
        if box is None or "edges" not in box:
            return None
        edges = box["edges"]
        if isinstance(edges, h5py.Group):  # time-dependent box is an S2 generalization
            return None
        lattice = np.asarray(edges, dtype=np.float64)
        boundary = box.get("boundary")
        if boundary is None:
            pbc = (True, True, True)
        else:
            pbc = tuple(_is_periodic(b) for b in np.asarray(boundary).reshape(-1)[:3])  # type: ignore[assignment]
        return Cell(lattice_vectors=lattice, pbc=pbc)

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.PARTIAL, notes="From a fixed-in-time box/edges."
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL, notes="From box/boundary."
                ),
            },
            max_frames=None,
            supports_variable_atom_count=True,
            required_fields=[],
            native_coordinate_system="cartesian",
        )


def _is_periodic(raw: object) -> bool:
    """H5MD ``boundary`` entry → periodic? Accepts bytes/str ``"periodic"``/``"none"``."""
    if isinstance(raw, bytes):
        raw = raw.decode()
    return str(raw) == "periodic"


def make_h5md_parser() -> H5MDParser:
    return H5MDParser()
