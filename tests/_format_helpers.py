"""Shared helpers for parser/exporter/round-trip tests (not a test module).

Two comparison notions are used across the format tests:

* **Golden comparison** — a parse of a source fixture against its hand-verified
  ``expected.canonical.json`` (Part 8 §3). The expectation is loaded *through the migration
  chain* (``schema.load_canonical``), so an expectation authored against an older schema is
  carried forward to the current one before the diff — a within-major schema bump needs zero
  fixture edits (the governance design, Part 8 §3.3). The fields that legitimately vary run to
  run are the parse-event bookkeeping in ``provenance.history`` (wall-clock timestamp and the
  tool/parser version strings) *and* the load-time ``migrate`` record the chain appends when the
  expectation lagged, so those are normalised away before comparison; everything else — including
  every scientific value and every ``parse_notes`` entry — must match byte-for-byte (DECISIONS.md
  D8). The migrate record itself is asserted by the corpus governance suite, not here.
* **Scientific equality** — for identity round-trips (``A → Canonical → A' → Canonical'``,
  Part 3 §3): the two objects must agree on all *scientific content* (frames, trajectory,
  simulation, user metadata). ``provenance`` is deliberately excluded: it records how *this
  particular file* was read (its filename, the coordinate system it happened to encode),
  which a faithful re-export may legitimately change without any loss of information.
"""

from __future__ import annotations

import io
import json
from typing import Any

from xtalate.schema import CanonicalObject, load_canonical
from xtalate.sdk import ParseResult
from xtalate.sdk.plugins import ParserPlugin


def parse_bytes(parser: ParserPlugin, data: bytes, *, filename: str | None = None) -> ParseResult:
    return parser.parse(io.BytesIO(data), filename=filename)


def _normalise_history(dumped: dict[str, Any]) -> dict[str, Any]:
    """Scrub the run-varying / load-time bookkeeping from ``provenance.history`` so the diff is over
    scientific content only: the wall-clock timestamp and tool/parser versions on every entry, and
    the whole ``migrate`` record the migration chain appends when a lagging expectation is loaded
    (a fresh parse never has one — dropping it keeps the two sides comparable)."""
    provenance = dumped.get("provenance")
    if not isinstance(provenance, dict):
        return dumped
    history = [e for e in provenance.get("history", []) if e.get("operation") != "migrate"]
    for entry in history:
        entry["timestamp"] = "<normalised>"
        entry["tool_version"] = "<normalised>"
        entry["parser_version"] = "<normalised>"
    provenance["history"] = history
    return dumped


def assert_matches_golden(produced: CanonicalObject, expected_json_text: str) -> None:
    # The expectation loads through the migration chain (it may be authored at an older schema than
    # the parser now produces); the fresh parse is already at the current schema.
    got = _normalise_history(json.loads(produced.model_dump_json()))
    want = _normalise_history(json.loads(load_canonical(expected_json_text).model_dump_json()))
    assert got == want


def scientific_dump(obj: CanonicalObject) -> dict[str, Any]:
    dumped: dict[str, Any] = json.loads(obj.model_dump_json())
    dumped.pop("provenance", None)
    return dumped


def assert_scientifically_equal(a: CanonicalObject, b: CanonicalObject) -> None:
    assert scientific_dump(a) == scientific_dump(b)
