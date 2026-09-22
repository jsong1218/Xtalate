"""Coverage-guided Atheris harness over every built-in parser (v1.8+v2.0 review, S7).

The continuous-fuzzing counterpart to :mod:`tests.fuzz.test_parser_fuzz`, which is the reviewable
*seed* corpus. Both assert the one invariant a robust parser must uphold on adversarial input:

    a parse of arbitrary bytes yields **either** a valid ``ParseResult`` **or** a ``ParseError``,
    and **nothing else** — no ``ValueError``/``KeyError``/``UnicodeDecodeError`` leaking through,
    no unhandled crash, no hang, no unbounded allocation.

The seed corpus (``tests/fuzz/test_parser_fuzz.py``) is a curated, deterministic battery; this
harness lets ClusterFuzzLite mutate those seeds under libFuzzer coverage guidance to reach edges no
hand-written seed anticipated. A crash Atheris reports here is a genuine robustness defect: fix it
in the owning parser by routing the escaped exception through the ``§5`` ``ParseError`` contract —
never by weakening the invariant.

The first byte of each input selects the parser (``data[0] % len(parsers)``); the remainder is the
payload. That keeps the seed corpus meaningful — a seed prefixed with a format's selector byte
deterministically targets that parser — while libFuzzer's mutations still explore every parser.

Run locally in a 3.11 venv with ``pip install .[fuzz]``::

    python tests/fuzz/fuzz_parsers.py -atheris_runs=20000 tests/fuzz/corpus/
"""

import io
import sys

import atheris

with atheris.instrument_imports():
    from xtalate.parsers import builtin_parsers
    from xtalate.sdk.results import ParseError

_PARSERS = list(builtin_parsers())


def TestOneInput(data: bytes) -> None:
    if len(data) < 2:
        return
    parser = _PARSERS[data[0] % len(_PARSERS)]
    try:
        parser.parse(io.BytesIO(data[1:]), filename="fuzz.dat")
    except ParseError:
        return  # the declared, graceful failure mode (§5 error contract)
    # A valid ParseResult is fine; any *other* exception propagates to Atheris as a crash.


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
