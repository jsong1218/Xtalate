"""The ``ParserPlugin`` facade over the four CIF stages (DECISIONS.md D65).

Thin by design: it decodes bytes, runs the stages in order, and translates the lexer's
syntax exception into the structured error contract. All the reading lives in the stages.
"""

from __future__ import annotations

from typing import BinaryIO

from xtalate.parsers._common import decode_text
from xtalate.parsers.cif._build import build
from xtalate.parsers.cif._document import build_document
from xtalate.parsers.cif._lexer import CifSyntaxError, tokenize
from xtalate.parsers.cif._validate import select_block
from xtalate.sdk import (
    CapabilityLevel,
    FieldCapability,
    FormatCapabilities,
    ParseError,
    ParseIssue,
    ParseResult,
    ParserPlugin,
)

FORMAT_ID = "cif"

# Tags whose presence in the first 64 KiB distinguishes a CIF from any other text format we
# read. A bare "data_" heading is not enough on its own — it is a plausible line in a comment
# or a title — so a structural tag must appear too.
_SIGNATURE_TAGS = ("_cell_length_", "_atom_site_", "_symmetry_", "_space_group_", "_chemical_")


class CifParser(ParserPlugin):
    """Crystallographic Information File reader (Part 3 §3).

    A CIF commonly stores only the **asymmetric unit** plus the symmetry operations that
    generate the rest. Since M18 those declared operations are applied, so ``atoms.*`` holds
    the full cell contents — this is reading the file as the CIF standard defines it, a
    format-defined fact rather than computed symmetry (Part 3 §3 n.13). The expansion is
    recorded in ``parse_notes`` (operation count, per-site multiplicities, merges) and the
    operation strings carry verbatim in ``simulation.extra["cif:symmetry_operations"]``.

    What is still refused, permanently, is a file declaring a non-``P 1`` symbol with **no**
    operation loop: the symbol alone does not say what to apply, and inferring it from a
    space-group table would be fabricating the structure rather than reading it (D66).
    """

    format_id = FORMAT_ID
    format_name = "Crystallographic Information File"
    version = "0.4.0"
    file_extensions = (".cif",)

    def sniff(self, head: bytes, filename: str | None) -> float:
        text = head.decode("utf-8", errors="replace")
        lowered = text.lower()
        has_block = any(line.lstrip().lower().startswith("data_") for line in lowered.splitlines())
        if not has_block:
            return 0.0
        if not any(tag in lowered for tag in _SIGNATURE_TAGS):
            return 0.0
        # An extension match on top of the structural signature is as unambiguous as sniffing
        # gets; the signature alone still wins comfortably against every other format we read,
        # none of which uses '_'-prefixed tags.
        if filename is not None and filename.lower().endswith(".cif"):
            return 1.0
        return 0.9

    def parse(self, stream: BinaryIO, *, filename: str | None) -> ParseResult:
        text = decode_text(stream.read(), format_id=self.format_id)
        try:
            tokens = tokenize(text)
            document = build_document(tokens)
        except CifSyntaxError as exc:
            raise ParseError(
                [
                    ParseIssue(
                        severity="error",
                        code="CIF_SYNTAX_ERROR",
                        message=exc.message,
                        location=f"line {exc.line}",
                    )
                ]
            ) from exc
        block, block_issues = select_block(document)
        canonical, build_issues = build(
            block,
            format_id=self.format_id,
            filename=filename,
            parser_version=f"{self.format_id}-parser {self.version}",
        )
        return ParseResult(canonical=canonical, issues=[*block_issues, *build_issues])

    def capabilities(self) -> FormatCapabilities:
        full = FieldCapability(level=CapabilityLevel.FULL)
        return FormatCapabilities(
            format_id=self.format_id,
            format_name=self.format_name,
            direction="read",
            fields={
                "atoms.symbols": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="From _atom_site_type_symbol (oxidation-state suffix split off) or "
                    "_atom_site_label; the raw type symbol is preserved per-atom.",
                ),
                "atoms.positions": full,
                "cell.lattice_vectors": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Built from _cell_length_* / _cell_angle_* with a≈+x and b in the "
                    "xy half-plane (crystallographic standard orientation).",
                ),
                "cell.pbc": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Always (T,T,T) by format definition; CIF carries no explicit PBC.",
                ),
                "cell.space_group": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Hermann-Mauguin or Hall symbol exactly as declared; never derived.",
                ),
                "electronic.charges": FieldCapability(
                    level=CapabilityLevel.PARTIAL,
                    notes="Only formal oxidation states, from a complete "
                    "_atom_type_oxidation_number loop; labelled 'formal_oxidation_state' in "
                    "simulation.extra. A partial declaration leaves the field unset.",
                ),
                "user_metadata.custom_per_atom": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Unmapped _atom_site columns (Wyckoff symbols, displacement "
                    "parameters) carried verbatim under 'cif:' keys, plus occupancy under "
                    "'cif:occupancy'.",
                ),
                "simulation.extra": FieldCapability(
                    level=CapabilityLevel.FULL,
                    notes="Bibliographic and free-text block tags carried verbatim.",
                ),
            },
            max_frames=1,
            required_fields=[],  # read side: absence is honoured, not required
            native_coordinate_system="fractional",
            lossy_notes=[
                "Only the first data_ block is read; further blocks are independent "
                "structures and are named in a warning, never silently skipped.",
                "Declared symmetry operations are applied, so atoms are the full cell, not the "
                "asymmetric unit; generated coordinates are wrapped into the cell and images "
                "coinciding within 0.05 Å are merged (Part 3 §3 n.13; DECISIONS.md D67).",
                "A non-P 1 symbol declared with no operation loop is refused, not guessed from "
                "a space-group table (DECISIONS.md D66).",
                "Occupancy is carried as a custom per-atom array under 'cif:occupancy', not "
                "modelled as a canonical field, and warns at parse (Part 3 §3 n.11).",
                "A type symbol's oxidation-state suffix ('Fe3+') is preserved verbatim but is "
                "not read as a charge; only a declared _atom_type_oxidation_number populates "
                "electronic.charges.",
            ],
        )


def make_cif_parser() -> CifParser:
    return CifParser()
