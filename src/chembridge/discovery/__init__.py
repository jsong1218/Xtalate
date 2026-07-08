"""Discovery — Format Sniffer + Information Discovery Engine (Part 3 §6).

Generic by construction: no per-format logic. Sniffs via each registered parser's
``sniff()`` (incl. the POSCAR⇄CONTCAR filename rule, Part 3 §6.1), parses via the
winning parser, and produces the ``DiscoveryReport`` from ``field_presence()``.
Sniffer + registry in M2; the Discovery Report in M6's inspect command.
"""

from chembridge.discovery.sniffer import (
    DEFAULT_ACCEPT_THRESHOLD,
    DEFAULT_AMBIGUITY_MARGIN,
    SniffCandidate,
    Sniffer,
    SniffResult,
)

__all__ = [
    "DEFAULT_ACCEPT_THRESHOLD",
    "DEFAULT_AMBIGUITY_MARGIN",
    "SniffCandidate",
    "SniffResult",
    "Sniffer",
]
