"""DeePMD directory I/O through the CLI (v1.5 M56-S1 read side; S2 write side).

``deepmd_npy`` is the first **directory** format: a directory goes in through the directory
sniff + ``parse_dir`` (never a stream), and a directory target writes a system directory under
``-o DIR`` (never a single file). These journeys pin the CLI contract: extXYZ → a DeePMD
system directory, a DeePMD directory → ``deepmd_npy`` (a dir-to-dir round-trip), the clean
usage error when ``-o`` is missing for a directory target, and the clean parse error for a
directory that is not a system.
"""

from __future__ import annotations

from pathlib import Path

from tests.golden.deepmd_npy._systems import (
    BOX_FLAT,
    H2O_COORDS,
    H2O_ENERGY,
    H2O_FORCES,
    write_system,
)
from xtalate.cli.main import EXIT_OK, EXIT_PARSE_ERROR, EXIT_USAGE, main
from xtalate.parsers.deepmd_npy import make_deepmd_npy_parser

# A stress-free two-frame extXYZ (no calculator stress → no ambiguous_stress_convention step, so
# the journeys exercise the directory write seam rather than the recovery surface).
TWO_FRAME_EXTXYZ = """2
frame1
C 0 0 0
O 0 0 1.1
2
frame2
C 0 0 0
O 0 0 1.2
"""


def _write_dir(files: dict[str, bytes], root: Path) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def test_convert_extxyz_to_deepmd_npy_writes_a_system_directory(tmp_path: Path) -> None:
    source = tmp_path / "train.xyz"
    source.write_text(TWO_FRAME_EXTXYZ)
    out = tmp_path / "system"
    rc = main(["convert", str(source), "--to", "deepmd_npy", "-o", str(out)])
    assert rc == EXIT_OK
    assert (out / "type.raw").is_file()
    assert (out / "type_map.raw").is_file()
    assert (out / "set.000" / "coord.npy").is_file()
    # The written directory re-reads as one DeePMD system through the same parser.
    files = {
        p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()
    }
    canonical = make_deepmd_npy_parser().parse_dir(files, dirname="system").canonical
    assert len(canonical.frames) == 2
    assert canonical.frames[0].atoms.symbols == ["C", "O"]


def test_convert_deepmd_directory_to_deepmd_npy_roundtrips(tmp_path: Path) -> None:
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
    )
    system = _write_dir(files, tmp_path / "in")
    out = tmp_path / "out"
    rc = main(["convert", str(system), "--to", "deepmd_npy", "-o", str(out)])
    assert rc == EXIT_OK
    # The round-trip keeps the source numbering byte-faithfully (the carried type files).
    assert (out / "type.raw").read_bytes() == files["type.raw"]
    assert (out / "type_map.raw").read_bytes() == files["type_map.raw"]


def test_convert_directory_input_to_single_file_target_works(tmp_path: Path) -> None:
    # A directory *in*, a single file *out* is an ordinary conversion: the directory read seam
    # feeds the same engine, so a DeePMD system converts to extXYZ like any other source.
    files = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])
    system = _write_dir(files, tmp_path / "in")
    out = tmp_path / "out.xyz"
    rc = main(["convert", str(system), "--to", "extxyz", "-o", str(out)])
    assert rc == EXIT_OK
    assert out.is_file()


def test_convert_a_bare_directory_fails_cleanly(tmp_path: Path) -> None:
    # A directory that is not a DeePMD system (no layout markers) → the generic directory sniff
    # finds nothing → a clean parse error (exit 4), never a traceback.
    bare = _write_dir({"readme.txt": b"not a system\n"}, tmp_path / "bare")
    rc = main(["convert", str(bare), "--to", "deepmd_npy", "-o", str(tmp_path / "out")])
    assert rc == EXIT_PARSE_ERROR


def test_directory_target_without_dash_o_is_a_usage_error(tmp_path: Path) -> None:
    source = tmp_path / "train.xyz"
    source.write_text(TWO_FRAME_EXTXYZ)
    rc = main(["convert", str(source), "--to", "deepmd_npy"])
    assert rc == EXIT_USAGE


def test_inspect_a_deepmd_system_directory(tmp_path: Path) -> None:
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
    )
    system = _write_dir(files, tmp_path / "in")
    rc = main(["inspect", str(system)])
    assert rc == EXIT_OK
