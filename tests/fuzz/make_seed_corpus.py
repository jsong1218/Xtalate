"""Materialize the ClusterFuzzLite seed corpus from the reviewable seed battery (S7).

The deterministic seeds in :mod:`tests.fuzz.test_parser_fuzz` (``_GENERIC`` + ``_TAILORED``) are
the human-curated starting points a coverage-guided fuzzer mutates from. This script writes each
one to ``tests/fuzz/corpus/`` as a standalone file, prefixed with the selector byte the harnesses
(:mod:`fuzz_parsers`) use to choose a parser — so a tailored seed deterministically targets the
parser it was written for, while libFuzzer's mutations still explore every parser.

``build.sh`` runs this at image-build time; it is also runnable by hand::

    python tests/fuzz/make_seed_corpus.py            # -> tests/fuzz/corpus/
    python tests/fuzz/make_seed_corpus.py OUT_DIR    # -> OUT_DIR/

The generic battery applies to every parser, so it is emitted once under selector byte 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable so ``tests.fuzz.*`` resolves whether this file is run by path
# (``python tests/fuzz/make_seed_corpus.py``) or from the ClusterFuzzLite build image.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.fuzz.test_parser_fuzz import _GENERIC, _TAILORED  # noqa: E402
from xtalate.parsers import builtin_parsers  # noqa: E402

_INDEX = {p.format_id: i for i, p in enumerate(builtin_parsers())}


def _write(out_dir: Path, name: str, selector: int, payload: bytes) -> None:
    (out_dir / name).write_bytes(bytes([selector % 256]) + payload)


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else Path(__file__).parent / "corpus"
    out_dir.mkdir(parents=True, exist_ok=True)

    for label, data in _GENERIC.items():
        _write(out_dir, f"generic_{label}", 0, data)

    for format_id, cases in _TAILORED.items():
        selector = _INDEX.get(format_id, 0)
        for label, data in cases:
            _write(out_dir, f"{format_id}_{label}", selector, data)

    written = len(list(out_dir.iterdir()))
    print(f"wrote {written} seed files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
