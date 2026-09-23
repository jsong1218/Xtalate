"""Parser fuzz seed corpus — the graceful-failure contract on malformed input (M37; R6).

R6 calls parser fuzzing a *permanent maintenance duty*; M37 is its scheduled instance (Part 9
§5.3). This module drives the reviewable **seed corpus** — a curated, deterministic battery of
malformed bytes (:mod:`tests.fuzz.seeds`) fed to every built-in parser — and asserts the one
invariant a robust parser must uphold on adversarial input —

    a parse of arbitrary bytes yields **either** a valid ``ParseResult`` **or** a ``ParseError``,
    and **nothing else**: no ``ValueError``/``KeyError``/``UnicodeDecodeError`` leaking through, no
    unhandled crash, no hang, no unbounded allocation.

That is the "files are data, never code / parsers fail through the §5 error contract" claim made
concrete (the same contract ``tests/parsers/test_xyz.py`` asserts for one case — "non-text bytes
must fail through the ParseError contract, not a raw UnicodeDecodeError"), generalized across all
seven Phase-1 formats.

**Why deterministic seeds, not random mutation.** A seed corpus is reproducible and reviewable, and
it cannot turn a benign CI run red on a mutation no one has seen — the property tests (D50) already
own randomized generation, over *valid* Canonical Objects. Continuous coverage-guided /
random-mutation fuzzing runs from these same seeds via Atheris under ClusterFuzzLite (the
``fuzz_parsers``/``fuzz_discovery`` harnesses); a seed that ever trips a *non*-graceful outcome is a
genuine robustness defect — record it as a regression seed and fix the parser, never weaken the
assertion to hide it.

The battery itself lives in :mod:`tests.fuzz.seeds` as pure data (no ``pytest`` import), so the
ClusterFuzzLite seed-corpus generator (:mod:`tests.fuzz.make_seed_corpus`) can read it inside a
fuzzing image that installs only the pure library. The corpus drives
:func:`xtalate.parsers.builtin_parsers` — the seven first-party parsers only, so the run is
independent of whatever third-party plugins happen to be installed.
"""

from __future__ import annotations

import io

import pytest

from tests.fuzz.seeds import _GENERIC, _TAILORED
from xtalate.parsers import builtin_parsers
from xtalate.sdk import ParseError, ParseResult
from xtalate.sdk.plugins import ParserPlugin


def _assert_graceful(parser: ParserPlugin, data: bytes, label: str) -> None:
    """The whole corpus's assertion: ``ParseError`` xor a valid ``ParseResult`` — never anything
    else. A leaked non-``ParseError`` exception (or a non-``ParseResult`` return) is the defect."""
    try:
        result = parser.parse(io.BytesIO(data), filename=f"fuzz.{parser.format_id}.{label}")
    except ParseError:
        return  # the graceful decline — the §5 contract
    except Exception as exc:  # noqa: BLE001 - catching the defect is the point of the test
        pytest.fail(
            f"{parser.format_id} leaked {type(exc).__name__} on seed {label!r} "
            f"instead of ParseError: {exc}"
        )
    assert isinstance(result, ParseResult), (
        f"{parser.format_id} returned {type(result).__name__} on seed {label!r}, not a ParseResult"
    )


_PARSERS = {p.format_id: p for p in builtin_parsers()}


@pytest.mark.parametrize("format_id", sorted(_PARSERS))
@pytest.mark.parametrize("label", sorted(_GENERIC))
def test_generic_battery_is_handled_gracefully(format_id: str, label: str) -> None:
    _assert_graceful(_PARSERS[format_id], _GENERIC[label], label)


@pytest.mark.parametrize(
    ("format_id", "label", "data"),
    [(fid, label, data) for fid, cases in _TAILORED.items() for label, data in cases],
)
def test_tailored_seeds_are_handled_gracefully(format_id: str, label: str, data: bytes) -> None:
    _assert_graceful(_PARSERS[format_id], data, label)


def test_corpus_covers_every_builtin_parser() -> None:
    # A guard so a newly-added first-party format cannot silently escape the fuzz corpus: every
    # built-in parser must appear in the tailored map (the generic battery already covers all).
    assert set(_TAILORED) == set(_PARSERS), (
        "every built-in parser needs at least one tailored fuzz seed; "
        f"missing: {set(_PARSERS) - set(_TAILORED)}"
    )
