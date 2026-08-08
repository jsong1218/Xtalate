"""Parser fuzz seed corpus — the graceful-failure contract on malformed input (M37; R6).

R6 calls parser fuzzing a *permanent maintenance duty*; M37 is its scheduled instance (Part 9
§5.3). This module is the reviewable **seed corpus**: a curated, deterministic battery of malformed
bytes fed to every built-in parser, asserting the one invariant a robust parser must uphold on
adversarial input —

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
random-mutation fuzzing is the documented gap this corpus seeds toward, ticketed in the M37 review
(``docs/security/REVIEW_M37.md``), not attempted here. If a seed ever trips a *non*-graceful outcome
that is a genuine robustness defect — record it as a regression seed and fix the parser, never
weaken the assertion to hide it.

The corpus drives :func:`xtalate.parsers.builtin_parsers` — the seven first-party parsers only, so
the run is independent of whatever third-party plugins happen to be installed.
"""

from __future__ import annotations

import io

import pytest

from xtalate.parsers import builtin_parsers
from xtalate.sdk import ParseError, ParseResult
from xtalate.sdk.plugins import ParserPlugin

# A generic battery every parser must survive — the shapes that most often break a hand-written
# parser: nothing at all, raw binary, mis-declared sizes, non-UTF-8 text, and a pathologically large
# count/line that must fail on EOF rather than pre-allocate.
_GENERIC: dict[str, bytes] = {
    "empty": b"",
    "nulls": b"\x00" * 8,
    "binary_garbage": bytes(range(256)) * 4,
    "utf16_bom": b"\xff\xfe" + "hello world".encode("utf-16-le"),
    "huge_count": b"999999999\ncomment\n",  # a count 9 orders past the body: EOF, not an OOM.
    "text_lines": b"not a real chemistry file\njust some words\n1 2 3\n",
    "one_token": b"42",
    "whitespace": b"   \n\t\n   \n",
    "long_line": b"A" * 200_000 + b"\n",
}

# Format-tailored malformations: a plausible header with a broken body, per format. These reach past
# the sniff/first-line guards into each parser's record-level parsing, where the interesting
# robustness edges live.
_TAILORED: dict[str, list[tuple[str, bytes]]] = {
    "xyz": [
        ("count_gt_atoms", b"5\ncomment\nH 0 0 0\nH 1 1 1\n"),
        ("nonnumeric_coord", b"1\nc\nH x y z\n"),
        ("count_not_int", b"abc\nc\nH 0 0 0\n"),
    ],
    "extxyz": [
        ("bad_lattice", b'2\nLattice="1 2 3" Properties=species:S:1:pos:R:3\nH 0 0 0\nH 1 1 1\n'),
        ("bad_properties", b"1\nProperties=garbage\nH 0 0 0\n"),
    ],
    "poscar": [
        ("bad_scale", b"c\nNOTFLOAT\n1 0 0\n0 1 0\n0 0 1\nH\n1\nDirect\n0 0 0\n"),
        ("counts_mismatch", b"c\n1.0\n1 0 0\n0 1 0\n0 0 1\nH O\n1\nDirect\n0 0 0\n"),
        ("short_lattice", b"c\n1.0\n1 0 0\n0 1 0\nH\n1\nDirect\n0 0 0\n"),
    ],
    "contcar": [
        ("bad_scale", b"c\nNOTFLOAT\n1 0 0\n0 1 0\n0 0 1\nH\n1\nDirect\n0 0 0\n"),
    ],
    "xdatcar": [
        ("no_config", b"c\n1.0\n1 0 0\n0 1 0\n0 0 1\nH\n1\n"),
        ("bad_lattice", b"c\n1.0\nx y z\n0 1 0\n0 0 1\nH\n1\nDirect config= 1\n0 0 0\n"),
    ],
    "cif": [
        ("unterminated_loop", b"data_x\nloop_\n_atom_site_label\n"),
        ("bad_number", b"data_x\n_cell_length_a NOTANUMBER\n"),
        ("empty_data", b"data_x\n"),
    ],
    "ase_traj": [
        ("truncated_pickle", b"\x80\x04\x95\x00\x00garbage"),
        ("text_as_traj", b"- Trajectory\nnot really\n"),
    ],
}


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
