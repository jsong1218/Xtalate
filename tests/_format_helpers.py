"""Shared helpers for parser/exporter/round-trip tests (not a test module).

Two comparison notions are used across the format tests:

* **Golden comparison** — a parse of a source fixture against its hand-verified
  ``expected.canonical.json`` (Part 8 §3). The only fields that legitimately vary run to
  run are the parse-event bookkeeping in ``provenance.history`` (wall-clock timestamp and
  the tool/parser version strings), so those are normalised before comparison; everything
  else — including every scientific value and every ``parse_notes`` entry — must match
  byte-for-byte after deserialisation (DECISIONS.md D8).
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

from xtalate.schema import CanonicalObject
from xtalate.sdk import ParseResult
from xtalate.sdk.plugins import ParserPlugin


def parse_bytes(parser: ParserPlugin, data: bytes, *, filename: str | None = None) -> ParseResult:
    return parser.parse(io.BytesIO(data), filename=filename)


def _normalise_history(dumped: dict[str, Any]) -> dict[str, Any]:
    for entry in dumped.get("provenance", {}).get("history", []):
        entry["timestamp"] = "<normalised>"
        entry["tool_version"] = "<normalised>"
        entry["parser_version"] = "<normalised>"
    return dumped


def assert_matches_golden(produced: CanonicalObject, expected_json_text: str) -> None:
    got = _normalise_history(json.loads(produced.model_dump_json()))
    want = _normalise_history(json.loads(expected_json_text))
    assert got == want


def scientific_dump(obj: CanonicalObject) -> dict[str, Any]:
    dumped: dict[str, Any] = json.loads(obj.model_dump_json())
    dumped.pop("provenance", None)
    return dumped


def assert_scientifically_equal(a: CanonicalObject, b: CanonicalObject) -> None:
    assert scientific_dump(a) == scientific_dump(b)
