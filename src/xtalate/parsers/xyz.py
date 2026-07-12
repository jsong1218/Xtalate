"""Plain XYZ parser (MASTER_SPEC Part 3 §3, §8.1).

Hand-rolled (DECISIONS.md D7): the grammar is trivial and hand-rolling avoids importing a
library that would invent defaults we would then have to launder back into absences. XYZ
carries exactly three things — element symbols, Cartesian positions (Å), and a free-text
comment line per frame — and *nothing* else. Every other canonical field is therefore
``None`` on the resulting object; that is the absence convention (Part 2 §2), not a gap to
be filled.

Grammar (one or more concatenated frames)::

    <atom count N>
    <comment: free text, may be empty>
    <symbol> <x> <y> <z>        # N lines
    ...                          # next frame's count, or EOF

Comment lines are information (they routinely hold frame labels / energies as free text),
so they are carried verbatim — one per frame — under
``user_metadata.custom_per_frame["xyz:comment"]`` (Part 3 §6.1 carry-through rule).
"""

from __future__ import annotations

from typing import BinaryIO

import numpy as np
from pydantic import JsonValue

from xtalate.parsers._common import build_provenance, decode_text
from xtalate.schema import (
    AtomsBlock,
    CanonicalObject,
    Frame,
    TrajectoryMetadata,
    UserMetadata,
)
from xtalate.schema.elements import is_valid_symbol
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "xyz"
_COMMENT_KEY = "xyz:comment"
# extXYZ (an XYZ superset, Part 3 §3 n.2) puts key=value metadata on the comment line;
# these markers let plain XYZ yield to a future extXYZ parser (M3c) on such files (§6.1).
_EXTXYZ_MARKERS = ("Lattice=", "Properties=")


def _looks_like_coordinate(line: str) -> bool:
    """True if ``line`` is ``<symbol> <float> <float> <float>`` (the XYZ atom row)."""
    parts = line.split()
    if len(parts) < 4:
        return False
    if not is_valid_symbol(parts[0]):
        return False
    try:
        float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return False
    return True


class XyzParser(ParserPlugin):
    format_id = FORMAT_ID
    format_name = "Plain XYZ"
    version = "0.1.0"
    file_extensions = (".xyz",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        # Cheap, never raises (§2): structural check on the first frame only.
        text = head.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            return 0.0
        try:
            count = int(lines[0].strip())
        except ValueError:
            return 0.0  # first line is not an atom count — not XYZ
        if count <= 0:
            return 0.0
        extxyz_comment = False
        if len(lines) < 3:
            # Header parses but we cannot see a coordinate row (tiny head); weak signal,
            # leaned on the .xyz filename hint if present.
            score = 0.4
        else:
            score = 0.9 if _looks_like_coordinate(lines[2]) else 0.3
            extxyz_comment = any(marker in lines[1] for marker in _EXTXYZ_MARKERS)
        if filename is not None and filename.lower().endswith(".xyz"):
            score = max(score, 0.7)
        if extxyz_comment:
            # extXYZ territory (a superset): cap last — after the filename hint, which does
            # not distinguish the two — so the more-expressive parser wins when registered.
            score = min(score, 0.6)
        return score

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        lines = decode_text(stream.read(), format_id=FORMAT_ID).splitlines()
        frames: list[Frame] = []
        comments: list[JsonValue] = []
        i = 0
        n_lines = len(lines)

        # Skip any leading blank lines, but a wholly blank/empty file is a parse error.
        while i < n_lines and lines[i].strip() == "":
            i += 1
        if i >= n_lines:
            raise ParseError(
                [ParseIssue(severity="error", code="XYZ_EMPTY", message="file contains no frames")]
            )

        frame_index = 0
        while i < n_lines:
            header = lines[i].strip()
            if header == "":
                i += 1
                continue  # tolerate blank separators between frames
            try:
                count = int(header)
            except ValueError as exc:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="XYZ_MALFORMED_HEADER",
                            message=f"expected an integer atom count, found {header!r}",
                            location=f"line {i + 1}",
                        )
                    ]
                ) from exc
            if count <= 0:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="XYZ_MALFORMED_HEADER",
                            message=f"atom count must be positive, found {count}",
                            location=f"line {i + 1}",
                        )
                    ]
                )
            # Comment line (may be empty; the line must still exist).
            if i + 1 >= n_lines:
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="XYZ_INCONSISTENT_ATOM_COUNT",
                            message=(
                                f"frame {frame_index} declares {count} atoms but the file ends "
                                "before its comment line and coordinates"
                            ),
                            location=f"frame {frame_index}",
                            recovery_hint="truncate_at_last_valid_frame",
                        )
                    ]
                )
            comment = lines[i + 1]
            body_start = i + 2
            body_end = body_start + count
            if body_end > n_lines:
                found = n_lines - body_start
                raise ParseError(
                    [
                        ParseIssue(
                            severity="error",
                            code="XYZ_INCONSISTENT_ATOM_COUNT",
                            message=(
                                f"frame {frame_index} declares {count} atoms but only {found} "
                                "coordinate lines are present before end of file"
                            ),
                            location=f"frame {frame_index}",
                            recovery_hint="truncate_at_last_valid_frame",
                        )
                    ]
                )

            symbols: list[str] = []
            positions: list[list[float]] = []
            for j in range(body_start, body_end):
                parts = lines[j].split()
                if len(parts) < 4:
                    # Fewer tokens than "<symbol> x y z" means the declared count is wrong:
                    # a coordinate row is missing (Part 3 §5 rule 4 — mid-file corruption).
                    raise ParseError(
                        [
                            ParseIssue(
                                severity="error",
                                code="XYZ_INCONSISTENT_ATOM_COUNT",
                                message=(
                                    f"frame {frame_index} declares {count} atoms but line "
                                    f"{j + 1} is not a '<symbol> x y z' coordinate row: "
                                    f"{lines[j]!r}"
                                ),
                                location=f"frame {frame_index}",
                                recovery_hint="truncate_at_last_valid_frame",
                            )
                        ]
                    )
                symbol = parts[0]
                if not is_valid_symbol(symbol):
                    raise ParseError(
                        [
                            ParseIssue(
                                severity="error",
                                code="XYZ_INVALID_SYMBOL",
                                message=(
                                    f"unknown element symbol {symbol!r} at line {j + 1} "
                                    "(use 'X' for a genuinely unknown species, Part 2 §3.3)"
                                ),
                                location=f"line {j + 1}",
                            )
                        ]
                    )
                try:
                    xyz = [float(parts[1]), float(parts[2]), float(parts[3])]
                except ValueError as exc:
                    raise ParseError(
                        [
                            ParseIssue(
                                severity="error",
                                code="XYZ_MALFORMED_COORDINATE",
                                message=f"non-numeric coordinate at line {j + 1}: {lines[j]!r}",
                                location=f"line {j + 1}",
                            )
                        ]
                    ) from exc
                symbols.append(symbol)
                positions.append(xyz)

            frames.append(
                Frame(
                    index=frame_index,
                    atoms=AtomsBlock(symbols=symbols, positions=np.asarray(positions, dtype=float)),
                )
            )
            comments.append(comment)
            frame_index += 1
            i = body_end

        # Comment lines are information — one per frame, carried verbatim (§6.1).
        user_metadata = UserMetadata(custom_per_frame={_COMMENT_KEY: comments})
        provenance = build_provenance(
            format_id=FORMAT_ID,
            filename=filename,
            original_coordinate_system="cartesian",
            source_units={"positions": "angstrom"},
            parse_notes=[
                "comment lines preserved in user_metadata.custom_per_frame['xyz:comment']"
            ],
        )
        # A single-frame XYZ is a static structure (trajectory=None, Part 2 §3.2); multiple
        # frames form a trajectory whose source declares no time base (timestep=None, §8.1).
        trajectory = None if len(frames) == 1 else TrajectoryMetadata(timestep=None)
        canonical = CanonicalObject(
            frames=frames,
            trajectory=trajectory,
            provenance=provenance,
            user_metadata=user_metadata,
        )
        return ParseResult(canonical=canonical)

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=FORMAT_ID,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": full,
                "atoms.positions": full,
                "user_metadata.custom_per_frame": FieldCapability(
                    level=CapabilityLevel.FULL, notes="Free-text comment line, one per frame."
                ),
            },
            max_frames=None,
            required_fields=[],
            native_coordinate_system="cartesian",
            lossy_notes=[],
        )
