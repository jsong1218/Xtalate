"""Peak-RSS probe for the streaming memory proof, run as a subprocess.

Each invocation performs *one* conversion of a pre-generated trajectory in one of two modes and
prints its peak resident-set size (bytes) to stdout. Running the two modes in **separate
processes** is what makes the comparison honest: ``ru_maxrss`` is a high-water mark that never
falls, so measuring streaming-then-materializing in one process would let whichever ran first hide
the other. The test orchestrates: generate once, probe ``stream`` and ``materialize`` separately,
and assert the streaming peak is a fraction of the materializing one.

Format-generic (M13): the source and target formats are passed as argv so the *same* probe backs
the M12 extXYZ→extXYZ proof and the M13 XDATCAR→extXYZ proof (XDATCAR being the format whose
ordinary size — 10⁴ configurations — is what forced chunking in the first place). Parser and
exporter are looked up in the default registry, so no format knowledge lives here.

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


def _run_stream(src_path: Path, out_path: Path, source_format: str, target_format: str) -> None:
    from xtalate.registry import default_registry
    from xtalate.sdk.streaming import export_stream

    registry = default_registry()
    parser = registry.get_parser(source_format)
    exporter = registry.get_exporter(target_format)
    with src_path.open("rb") as src:
        # Hand the parser the open file directly so it never slurps the whole trajectory into one
        # string — the strongest memory bound.
        stream = parser.parse_stream(src, filename=src_path.name)
        with out_path.open("wb") as out:
            export_stream(exporter, stream.header, stream.frames(), out)


def _run_materialize(
    src_path: Path, out_path: Path, source_format: str, target_format: str
) -> None:
    import io

    from xtalate.registry import default_registry

    registry = default_registry()
    parser = registry.get_parser(source_format)
    exporter = registry.get_exporter(target_format)
    data = src_path.read_bytes()
    canonical = parser.parse(io.BytesIO(data), filename=src_path.name).canonical
    buf = io.BytesIO()
    exporter.export(canonical, buf)
    out_path.write_bytes(buf.getvalue())


def main() -> int:
    mode = sys.argv[1]
    if mode == "baseline":
        # Import the conversion machinery so the floor includes it, then do nothing.
        import xtalate.registry  # noqa: F401
        import xtalate.sdk.streaming  # noqa: F401
    else:
        src_path = Path(sys.argv[2])
        out_path = Path(sys.argv[3])
        # Source/target formats default to the M12 extXYZ→extXYZ pass-through when omitted.
        source_format = sys.argv[4] if len(sys.argv) > 4 else "extxyz"
        target_format = sys.argv[5] if len(sys.argv) > 5 else "extxyz"
        if mode == "stream":
            _run_stream(src_path, out_path, source_format, target_format)
        elif mode == "materialize":
            _run_materialize(src_path, out_path, source_format, target_format)
        else:  # pragma: no cover - guarded by the test's fixed argv
            raise SystemExit(f"unknown mode {mode!r}")
    print(_peak_rss_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
