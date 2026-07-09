"""Format Sniffer (MASTER_SPEC Part 3 §6.1).

Generic by construction — **no per-format logic** (§6.1). Every registered parser scores
the file head via its own ``sniff(head, filename)``; the sniffer only ranks the scores and
applies two instance-configurable thresholds:

* ``accept_threshold`` (default **0.5**): the top score must reach this or the file is
  ``UNKNOWN_FORMAT`` (``format_id = None``), all candidates recorded so the caller can see
  why — a low-confidence guess silently applied would be a misparse waiting to happen.
* ``ambiguity_margin`` (default **0.2**): if the top two scores are within this, the result
  is flagged ``ambiguous`` and every candidate is kept as evidence for a user override.

Format-specific tie preferences are expressed through the *parsers' own scores and
filename handling*, not hardcoded here. The **POSCAR ⇄ CONTCAR** case (§6.1) is the
canonical example: each parser returns 1.0 for its exact conventional filename, and the
more-specific CONTCAR reading scores marginally lower on a generic file, so POSCAR wins a
nameless tie while the ambiguity is still surfaced — all without the sniffer knowing either
format exists. When two formats genuinely tie, the deterministic pick is the top score,
ties broken by ``format_id`` order, always with ``ambiguous=True``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from chembridge.capabilities import Registry

DEFAULT_ACCEPT_THRESHOLD = 0.5
DEFAULT_AMBIGUITY_MARGIN = 0.2
HEAD_SIZE = 64 * 1024  # Parsers see at most the first 64 KiB (§2).


class SniffCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: str
    confidence: float


class SniffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_id: str | None  # None => UNKNOWN_FORMAT (top score below accept_threshold).
    confidence: float  # The top score (0.0 when there are no parsers / unknown).
    ambiguous: bool  # True when the top two scores are within ambiguity_margin.
    candidates: list[SniffCandidate]  # All scored parsers, highest first — the sniff evidence.


class Sniffer:
    def __init__(
        self,
        registry: Registry,
        *,
        accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
        ambiguity_margin: float = DEFAULT_AMBIGUITY_MARGIN,
    ) -> None:
        self._registry = registry
        self.accept_threshold = accept_threshold
        self.ambiguity_margin = ambiguity_margin

    def sniff(self, data: bytes, filename: str | None = None) -> SniffResult:
        head = data[:HEAD_SIZE]
        candidates: list[SniffCandidate] = []
        for parser in self._registry.parsers():
            try:
                score = float(parser.sniff(head, filename))
            except Exception:
                # sniff() "must never raise" (§2); a misbehaving plugin scores 0, never
                # crashes detection of the other formats.
                score = 0.0
            score = max(0.0, min(1.0, score))
            candidates.append(SniffCandidate(format_id=parser.format_id, confidence=score))

        # Highest confidence first; ties broken by format_id for a deterministic winner.
        candidates.sort(key=lambda c: (-c.confidence, c.format_id))

        if not candidates:
            return SniffResult(format_id=None, confidence=0.0, ambiguous=False, candidates=[])

        best = candidates[0]
        if best.confidence < self.accept_threshold:
            # UNKNOWN_FORMAT: below the acceptance bar. Report candidates so the caller can
            # override, but select nothing (§6.1).
            return SniffResult(
                format_id=None, confidence=best.confidence, ambiguous=False, candidates=candidates
            )

        runner_up = candidates[1].confidence if len(candidates) > 1 else 0.0
        ambiguous = (best.confidence - runner_up) < self.ambiguity_margin
        return SniffResult(
            format_id=best.format_id,
            confidence=best.confidence,
            ambiguous=ambiguous,
            candidates=candidates,
        )
