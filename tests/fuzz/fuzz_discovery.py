"""Coverage-guided Atheris harness over the Information Discovery Engine (v1.8+v2.0 review, S7).

The Discovery Engine sniffs an arbitrary file and reports what is present/absent without
converting it (Part 3 §6). It is a second attack surface on the same untrusted bytes the parser
harness fuzzes, reached through a *different* path — the format sniffer selects the parser, then a
frame-counting pre-pass runs before the materialized parse. Its declared graceful failure modes are
``ParseError`` (including the ``UNKNOWN_FORMAT`` decline when nothing sniffs) and
``FrameLimitExceeded`` (the ``max_frames`` gate the harness arms so a pathological trajectory is
refused, not materialized). Anything else — an unhandled exception, a hang, an OOM — is a defect,
exactly as for the parser harness.

Run locally in a 3.11 venv with ``pip install .[fuzz]``::

    python tests/fuzz/fuzz_discovery.py -atheris_runs=20000 tests/fuzz/corpus/
"""

import sys

import atheris

with atheris.instrument_imports():
    from xtalate.discovery.engine import DiscoveryEngine
    from xtalate.registry import default_registry
    from xtalate.sdk.results import FrameLimitExceeded, ParseError

# The engine is stateless across calls and holds only the (immutable) default registry, so it is
# built once at import time rather than per input.
_ENGINE = DiscoveryEngine(default_registry())

# Bound the frame pre-pass so a mutated count field is refused (FrameLimitExceeded) rather than
# driving an unbounded pre-scan — the gate the HTTP inspect path relies on (M39-S3).
_MAX_FRAMES = 10_000


def TestOneInput(data: bytes) -> None:
    if not data:
        return
    try:
        _ENGINE.discover(data, filename="fuzz.dat", max_frames=_MAX_FRAMES)
    except (ParseError, FrameLimitExceeded):
        return  # the declared, graceful decline paths
    # A valid DiscoveryReport is fine; any *other* exception propagates to Atheris as a crash.


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
