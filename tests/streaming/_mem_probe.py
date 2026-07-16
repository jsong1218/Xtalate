"""Peak-RSS probe for the M12 memory proof, run as a subprocess (``tests.streaming._mem_probe``).

Each invocation performs *one* conversion of a pre-generated extXYZ trajectory in one of two modes
and prints its peak resident-set size (bytes) to stdout. Running the two modes in **separate
processes** is what makes the comparison honest: ``ru_maxrss`` is a high-water mark that never
falls, so measuring streaming-then-materializing in one process would let whichever ran first hide
the other. The test orchestrates: generate once, probe ``stream`` and ``materialize`` separately,
and assert the streaming peak is a fraction of the materializing one.

Modes:
* ``baseline`` — import the world and read nothing; the interpreter+imports floor to subtract.
* ``stream``   — ``parse_stream`` → ``export_stream`` file→file, one frame resident.
* ``materialize`` — whole-file ``parse`` → whole-object ``export``, the whole trajectory resident.
"""

from __future__ import annotations

import resource
import sys
from pathlib import Path


def _peak_rss_bytes() -> int:
    """Peak RSS in bytes, normalizing the platform unit (macOS reports bytes, Linux kibibytes)."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw if sys.platform == "darwin" else raw * 1024


def _run_stream(src_path: Path, out_path: Path) -> None:
    from xtalate.exporters.extxyz import ExtxyzExporter
    from xtalate.parsers.extxyz import ExtxyzParser
    from xtalate.sdk.streaming import export_stream

    parser = ExtxyzParser()
    exporter = ExtxyzExporter()
    with src_path.open("rb") as src:
        # parse_as_stream reads the bytes; for the strongest bound we hand the parser the open file
        # directly so it never slurps the whole trajectory into one string.
        stream = parser.parse_stream(src, filename=src_path.name)
        with out_path.open("wb") as out:
            export_stream(exporter, stream.header, stream.frames(), out)


def _run_materialize(src_path: Path, out_path: Path) -> None:
    import io

    from xtalate.exporters.extxyz import ExtxyzExporter
    from xtalate.parsers.extxyz import ExtxyzParser

    parser = ExtxyzParser()
    exporter = ExtxyzExporter()
    data = src_path.read_bytes()
    canonical = parser.parse(io.BytesIO(data), filename=src_path.name).canonical
    buf = io.BytesIO()
    exporter.export(canonical, buf)
    out_path.write_bytes(buf.getvalue())


def main() -> int:
    mode = sys.argv[1]
    if mode == "baseline":
        # Import the conversion machinery so the floor includes it, then do nothing.
        import xtalate.exporters.extxyz  # noqa: F401
        import xtalate.parsers.extxyz  # noqa: F401
    else:
        src_path = Path(sys.argv[2])
        out_path = Path(sys.argv[3])
        if mode == "stream":
            _run_stream(src_path, out_path)
        elif mode == "materialize":
            _run_materialize(src_path, out_path)
        else:  # pragma: no cover - guarded by the test's fixed argv
            raise SystemExit(f"unknown mode {mode!r}")
    print(_peak_rss_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
