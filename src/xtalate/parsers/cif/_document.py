"""Stage 2 of the CIF reader: tokens → a CIF document (DECISIONS.md D65).

This is the format's own data model — named ``data_`` blocks, each holding tag→value pairs and
``loop_`` tables — and it is still not Xtalate's. Nothing here imports ``xtalate.schema``.

**The API shape is a deliberate decision, not an accident.** ``CifDocument.blocks``,
``CifBlock.find_pair(tag)`` and ``CifBlock.find_loop(tag)`` mirror ``gemmi.cif``'s
``Document``/``Block`` surface so that adopting gemmi later means deleting ``_lexer`` and
``_document`` and re-exposing the same three calls — leaving ``_validate`` and ``_build``
untouched. An idiosyncratic model would keep the seam but forfeit the benefit (D65).

Two CIF conventions are resolved at this layer because both are purely lexical:

* **Tags are case-insensitive.** ``_Cell_Length_A`` and ``_cell_length_a`` are one tag. Lookup
  normalizes to lowercase, and ``CifBlock.spellings`` records each tag's original casing so this
  document layer remains a faithful account of the file it read.

  **Known limitation, stated because the docstring used to claim otherwise.** Nothing downstream
  reads ``spellings``: the builder keys carry-through off the lowercased tags, so a source's
  ``_space_group_IT_number`` becomes ``cif:space_group_it_number`` and is written back lowercased.
  Tag case is laundered on every round trip. That is cosmetic — CIF tags are case-insensitive, so
  no reader is misled and no value changes — but it is *not* the "carry-through reproduces what
  the file said (**P1**)" this comment previously asserted, and a live P1 promise no code keeps is
  worse than an acknowledged gap. Honouring it means carrying the spelling alongside the canonical
  key, which changes a canonical path's derivation and wants its own decision; until then this is
  the honest description.
* **Bare ``?`` and ``.`` are absence.** CIF's "unknown" and "inapplicable" markers become
  ``None`` here, which is exactly the Canonical Model's absence convention (**P3**) — a value
  the source did not state never reaches the builder as a string to be misread as data. Quoted
  ``'?'`` is a literal and is preserved, which is why the lexer tracked quoting.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xtalate.parsers.cif._lexer import CifSyntaxError, Token

_UNKNOWN = "?"  # CIF "value is unknown"
_INAPPLICABLE = "."  # CIF "value does not apply to this item"


def _resolve(token: Token) -> str | None:
    """A token's value, with the bare absence markers mapped to ``None`` (P3)."""
    if not token.quoted and token.value in (_UNKNOWN, _INAPPLICABLE):
        return None
    return token.value


@dataclass
class CifLoop:
    """One ``loop_`` table: parallel columns addressed by tag."""

    tags: list[str]  # lowercase, in file order
    spellings: list[str]  # original casing, parallel to ``tags``
    rows: list[list[str | None]]
    line: int  # 1-based line of the ``loop_`` keyword

    def column(self, tag: str) -> list[str | None] | None:
        """The named column, or ``None`` if this loop does not carry that tag."""
        try:
            index = self.tags.index(tag.lower())
        except ValueError:
            return None
        return [row[index] for row in self.rows]

    def has(self, tag: str) -> bool:
        return tag.lower() in self.tags


@dataclass
class CifBlock:
    """One ``data_`` block. In CIF a block is an independent structure, not a frame."""

    name: str
    line: int
    pairs: dict[str, str | None] = field(default_factory=dict)
    spellings: dict[str, str] = field(default_factory=dict)
    pair_lines: dict[str, int] = field(default_factory=dict)
    loops: list[CifLoop] = field(default_factory=list)

    def find_pair(self, *tags: str) -> str | None:
        """The value of the first of ``tags`` present as a tag→value pair.

        Accepts several spellings because CIF renamed a whole family of tags between the
        legacy ``_symmetry_*`` set and the current ``_space_group_*`` set, and real files use
        both — often in the same file. Returns ``None`` both when the tag is absent and when it
        is present with an absence marker: the two are equivalent everywhere this is called, since
        a tag carrying ``?`` states nothing, which is what an absent tag states too.
        """
        for tag in tags:
            value = self.pairs.get(tag.lower())
            if value is not None:
                return value
        return None

    def line_of(self, *tags: str) -> int:
        """Source line of the first of ``tags`` present, falling back to the block heading."""
        for tag in tags:
            if tag.lower() in self.pair_lines:
                return self.pair_lines[tag.lower()]
        return self.line

    def find_loop(self, tag: str) -> CifLoop | None:
        """The loop carrying ``tag``, or ``None``."""
        for loop in self.loops:
            if loop.has(tag):
                return loop
        return None


@dataclass
class CifDocument:
    blocks: list[CifBlock] = field(default_factory=list)


def build_document(tokens: list[Token]) -> CifDocument:
    """Assemble a :class:`CifDocument` from a token stream.

    Raises :class:`CifSyntaxError` for structural defects the token stream makes unambiguous —
    a tag or loop outside any ``data_`` block, a ``loop_`` with no tags, a value with no tag to
    attach to. Semantic checks ("is there a cell?") are stage 3's job, not this function's.
    """
    document = CifDocument()
    block: CifBlock | None = None
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "data":
            block = CifBlock(name=token.value, line=token.line)
            document.blocks.append(block)
            index += 1
            continue
        if block is None:
            raise CifSyntaxError(
                f"{token.kind} {token.value!r} appears before any 'data_' block heading",
                token.line,
            )
        if token.kind == "loop":
            index = _read_loop(tokens, index, block)
            continue
        if token.kind == "tag":
            index = _read_pair(tokens, index, block)
            continue
        raise CifSyntaxError(f"value {token.value!r} has no preceding tag", token.line)
    return document


def _read_pair(tokens: list[Token], index: int, block: CifBlock) -> int:
    """Read a ``_tag value`` pair beginning at ``tokens[index]``."""
    tag = tokens[index]
    if index + 1 >= len(tokens) or tokens[index + 1].kind != "value":
        raise CifSyntaxError(f"tag {tag.value!r} has no value", tag.line)
    key = tag.value.lower()
    block.pairs[key] = _resolve(tokens[index + 1])
    block.spellings[key] = tag.value
    block.pair_lines[key] = tag.line
    return index + 2


def _read_loop(tokens: list[Token], index: int, block: CifBlock) -> int:
    """Read a ``loop_`` header and its value rows beginning at ``tokens[index]``."""
    loop_line = tokens[index].line
    index += 1
    tags: list[str] = []
    spellings: list[str] = []
    while index < len(tokens) and tokens[index].kind == "tag":
        spellings.append(tokens[index].value)
        tags.append(tokens[index].value.lower())
        index += 1
    if not tags:
        raise CifSyntaxError("'loop_' is not followed by any tags", loop_line)

    values: list[str | None] = []
    while index < len(tokens) and tokens[index].kind == "value":
        values.append(_resolve(tokens[index]))
        index += 1
    if len(values) % len(tags) != 0:
        raise CifSyntaxError(
            f"loop with {len(tags)} columns has {len(values)} values, which is not a whole "
            f"number of rows ({len(values) % len(tags)} left over)",
            loop_line,
        )
    rows = [values[i : i + len(tags)] for i in range(0, len(values), len(tags))]
    block.loops.append(CifLoop(tags=tags, spellings=spellings, rows=rows, line=loop_line))
    return index
