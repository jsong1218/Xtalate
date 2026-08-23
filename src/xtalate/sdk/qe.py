"""Shared Quantum ESPRESSO conventions (v1.4 M50-S3 / M51-S1; D191, D192).

The single shared spot for the QE format's **identical key strings and label rule** — imported
by both the pw.x input *parser* (``parsers/qe_pw_in.py``, which reads them) and the pw.x input
*exporter* (``exporters/qe_pw_in.py``, which writes them back), so the two sides of the format
can never drift (the ``sdk.lammps`` relocation precedent, M47-S1/D177: a shared core moved below
the parser/exporter layers for the import-linter contract, because ``xtalate.parsers`` and
``xtalate.exporters`` are independent layers that may not import each other).

Why these live in the SDK rather than in a parser module: the M51 exporter must reuse the
*identical* strings the M50 parser wrote (terminology is binding — a forked key string would
silently break the ``qe_pw_in → qe_pw_in`` carry-back round-trip), and the import-linter layers
contract forbids ``exporters → parsers``. The SDK is the one layer both may import.

* **The carry-through key strings** — ``qe:pseudopotentials`` (label → filename, the M50-S3
  promotion), ``qe_pw_in:namelists`` / ``qe_pw_in:unmapped_cards`` (unconsumed namelist entries
  / unrecognized cards, Part 2 §6.1), and ``qe_pw_in:atomic_species`` (the verbatim declared
  table). The exporter declares exactly these four as its ``writable_custom_keys`` so the
  pre-flight diff predicts **no** loss for ``qe_pw_in → qe_pw_in``.
* **``_CONSUMED_SYSTEM_KEYS``** — the ``&system`` facts the reader consumes structurally; the
  exporter refuses to write a carried spelling of any of them (it computes ``ibrav``/``nat``/
  ``ntyp`` itself, and the ``celldm``/``A`` spellings contradict explicit ``CELL_PARAMETERS``).
* **``_SIMULATION_EXTRA_KEYS``** — the namelist → key mapping of the recognized simulation
  context M50 routes to ``simulation.extra``; the exporter writes those keys back into the *same*
  namelist, so the round-trip restores ``ecutwfc``/``calculation``/… to the shell they came from.
* **``species_symbol``** — QE's documented ``ATOMIC_SPECIES`` label → element rule (the element
  is the leading 1–2 characters that form an element symbol, tried 2 then 1 — ``Fe1`` → Fe,
  ``O_vac`` → O). The parser resolves labels with it (M50-S3, D191); the exporter uses the same
  rule to reconstruct which atom carried which label when writing the table back. Composes the
  shared ``normalize_symbol`` — the element table stays the single authority; only QE's
  *decoration* rule lives here. The reserved pseudo-element ``X`` (the schema's unknown-species
  marker) is a symbol in that table, so ``Xx`` resolves to the marker, never to a real element.

This module imports only ``xtalate.schema`` — the layer both sides already depend on.
"""

from __future__ import annotations

from collections.abc import Mapping

from xtalate.schema.elements import normalize_symbol

#: The custom_global key the full ATOMIC_SPECIES table rides under: the mass and
#: pseudopotential columns have no canonical home in this milestone and are **never
#: dropped** (P1). M50-S3 additionally promotes masses → atoms.masses and
#: pseudopotential filenames → user_metadata.custom_global["qe:pseudopotentials"] (label →
#: filename); the verbatim declared table stays here.
_ATOMIC_SPECIES_KEY = "qe_pw_in:atomic_species"
#: The custom_global key pseudopotential filenames ride under (label → filename), the
#: carry-through routing for scientifically load-bearing content with no canonical model.
_PSEUDOPOTENTIALS_KEY = "qe:pseudopotentials"
#: The custom_global key unconsumed namelist entries ride under (per-namelist dict), and
#: the key unrecognized cards ride under (list of {card, unit, lines}). M50-S3 routes
#: these under the Part 2 §6.1 carry-through rule with the QEIN_UNMAPPED_ENTRY_CARRIED
#: warning.
_NAMELISTS_KEY = "qe_pw_in:namelists"
_UNMAPPED_CARDS_KEY = "qe_pw_in:unmapped_cards"

#: The &system facts the reader consumes; everything else in &system (and every other
#: namelist) rides the carry under the Part 2 §6.1 routing rule. The exporter computes
#: ``ibrav``/``nat``/``ntyp`` itself and refuses any carried spelling of this set.
_CONSUMED_SYSTEM_KEYS = frozenset(
    {"ibrav", "nat", "ntyp", "celldm", "a", "b", "c", "cosab", "cosac", "cosbc"}
)

#: The namelist entries M50-S3 *recognizes* as simulation context and promotes to
#: ``simulation.extra`` (the §6.1 routing rule: recognized simulation/method properties live
#: in ``simulation.extra``; everything else rides the carry). Promoted here means consumed —
#: the entry is not also carried in ``qe_pw_in:namelists`` (no double-report). QE's
#: calculation type + the convergence/cutoff parameters per the plan (D191); values are
#: stored as strings per the ``SimulationMetadata.extra: dict[str, str]`` contract. The
#: exporter writes each key back into the namelist this mapping names.
_SIMULATION_EXTRA_KEYS: Mapping[str, frozenset[str]] = {
    "control": frozenset({"calculation", "ecutwfc", "ecutrho"}),
    "system": frozenset({"degauss", "smearing", "occupations"}),
    "electrons": frozenset({"conv_thr"}),
}


def species_symbol(label: str) -> tuple[str | None, str]:
    """QE's documented label → element rule: the element is the leading 1–2 characters of
    an ``ATOMIC_SPECIES`` label that form an element symbol, matched case-insensitively
    (the 2-character prefix is tried first, then the 1-character — so ``Fe1`` → Fe,
    ``O_vac`` → O, ``fe`` → Fe, and ``NaCl`` → Na, while ``Zz`` → None). Composes the
    shared ``normalize_symbol`` — the element table stays the single authority; only QE's
    *decoration* rule (labels are element symbols with optional trailing characters,
    per QE's documented ``ATOMIC_SPECIES`` convention) lives here, so M52's output parser
    resolves labels identically. Note that the reserved pseudo-element ``X`` (the schema's
    unknown-species marker) is a symbol in that table, so ``Xx`` resolves to the marker
    ``X`` (recorded), never to a real element. Returns ``(symbol, decoration)`` where
    ``decoration`` is the label's trailing characters beyond the matched prefix (``""``
    for a plain label) and ``(None, label)`` when no leading 1–2 characters form an
    element.
    """
    stripped = label.strip()
    for n in (2, 1):
        symbol = normalize_symbol(stripped[:n])
        if symbol is not None:
            return symbol, stripped[n:]
    return None, stripped
