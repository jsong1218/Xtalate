"""Shared exporter helpers (MASTER_SPEC Part 3 §2, Part 4 §1).

The mirror of ``parsers._common``: boilerplate every VASP-family exporter needs, kept in one
place so each format module stays focused on its grammar. Imports only ``schema``/``sdk``,
never another exporter's module — the P2 boundary holds within the exporter layer too.
"""

from __future__ import annotations


def group_by_element(symbols: list[str]) -> tuple[list[str], list[int], list[int]]:
    """Group atoms by element in first-occurrence order.

    The VASP family (POSCAR, CONTCAR, XDATCAR) declares a species line and a counts line, so
    one element's atoms must be *contiguous* in the file. Returns ``(order, permutation,
    counts)`` where ``order`` is the element sequence, ``permutation[i]`` is the source index
    written at output position *i* (the Part 5 permutation map), and ``counts`` is the per-element
    atom count.

    Both ``export`` (to write the file) and ``atom_permutation`` (to report the map to the
    Validation Engine) derive from this one function, so what an exporter writes and what it
    claims to have written can never disagree.
    """
    order: list[str] = []
    groups: dict[str, list[int]] = {}
    for i, sym in enumerate(symbols):
        if sym not in groups:
            groups[sym] = []
            order.append(sym)
        groups[sym].append(i)
    permutation = [i for sym in order for i in groups[sym]]
    counts = [len(groups[sym]) for sym in order]
    return order, permutation, counts
