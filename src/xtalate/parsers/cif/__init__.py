"""CIF parser — the one format read by a package rather than a module (DECISIONS.md D65).

Four stages, strictly one-way::

    text ─► _lexer ─► _document ─► _validate ─► _build ─► CanonicalObject
            tokens    CIF blocks   CIF rules    canonical rules

``_lexer`` and ``_document`` know CIF syntax only; ``_validate`` checks what is expressible
without the Canonical Model; ``_build`` is the only stage that imports ``xtalate.schema``. That
line is what keeps the stages from collapsing into each other, and it is what makes stages 1–2
replaceable (by gemmi, or anything else) without touching the validation rules, the
``ParseError`` contract, or the builder.
"""

from __future__ import annotations

from xtalate.parsers.cif._plugin import FORMAT_ID, CifParser, make_cif_parser

__all__ = ["FORMAT_ID", "CifParser", "make_cif_parser"]
