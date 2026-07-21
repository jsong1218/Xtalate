"""The real-world corpus: third-party files vendored verbatim (v0.4 M20, DECISIONS.md D70).

Sibling to ``tests/golden/``, and deliberately not part of it. A golden case asserts what a
file *should* produce, verified by hand. A wild case asserts what a real file *does* produce,
triaged by hand — the difference between a specification and a confrontation. Both are governed
by ``tests/golden/_governance.py``; only the expectation differs.

**Axis coverage.** M20 names seven syntax axes the batch should span. Six are covered by the
cases in ``cod/``: legacy ``_symmetry_*`` spelling, mixed-case tags, ``?``/``.`` unknown-value
markers, uncertainty parentheses, occupancy < 1, and oxidation-state symbols. Several cases
carry more than one, which is how real files come.

**Multi-block is not covered, and could not be.** COD serves one structure per file by
construction, so its entries are single-block by construction too: a sample of ~60 entries drawn
across the whole numbering space turned up not one file with a second ``data_`` block. Multi-block
CIFs are real — multi-phase refinements and publication supplements produce them — but they are
not what a structure database distributes, and no amount of further sampling here would have
found one. That axis therefore stays with the synthetic fixture that already covers it
(``CIF_ADDITIONAL_BLOCKS_NOT_READ``), and this paragraph exists so that a later reader finds a
recorded reason rather than an apparent oversight. Sourcing a real multi-block CIF means finding
a differently-shaped supplier, not searching COD harder.
"""
