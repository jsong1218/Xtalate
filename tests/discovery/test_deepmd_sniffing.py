"""Directory sniffing for ``deepmd_npy`` (v1.5 M56-S1, Part 3 §6.1).

The sniffer stays generic: it scores a directory *listing* via each registered parser's
``sniff_dir`` hook — no per-format logic in discovery. A DeePMD system directory selects
``deepmd_npy``; a single file never does (a file head always scores 0.0); a bare directory
without the marker files is ``UNKNOWN_FORMAT``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.golden.deepmd_npy._systems import BOX_FLAT, H2O_COORDS, write_system
from xtalate.discovery import DiscoveryEngine
from xtalate.discovery.sniffer import Sniffer
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

_REGISTRY = default_registry()
_SNIFFER = Sniffer(_REGISTRY)

_SYSTEM = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])


def _write(files: dict[str, bytes]) -> Path:
    root = Path(tempfile.mkdtemp())
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def test_system_directory_sniffs_as_deepmd_npy() -> None:
    sniff = _SNIFFER.sniff_dir(list(_SYSTEM), "system")
    assert sniff.format_id == "deepmd_npy"
    assert sniff.confidence == 1.0


def test_a_single_file_never_sniffs_as_deepmd_npy() -> None:
    sniff = _SNIFFER.sniff(_SYSTEM["type.raw"], "type.raw")
    assert sniff.format_id is None


def test_a_bare_directory_without_markers_is_unknown() -> None:
    sniff = _SNIFFER.sniff_dir(["readme.txt", "notes.md"], "empty")
    assert sniff.format_id is None


def test_partial_listing_scores_below_the_accept_threshold() -> None:
    sniff = _SNIFFER.sniff_dir(["type.raw"], "partial")
    assert sniff.format_id is None  # 0.35 < the accept threshold → not selected


def test_discover_dir_reports_a_deepmd_system() -> None:
    root = _write(_SYSTEM)
    report = DiscoveryEngine(_REGISTRY).discover_dir(_SYSTEM, dirname=root.name)
    assert report.format["format_id"] == "deepmd_npy"
    assert report.structure["frame_count"] == 1
    assert report.structure["species"] == ["O", "H"]  # first-occurrence order (§6.3)


def test_discover_dir_refuses_a_directory_without_markers() -> None:
    with pytest.raises(ParseError) as excinfo:
        DiscoveryEngine(_REGISTRY).discover_dir({"readme.txt": b"hi"}, dirname="empty")
    assert excinfo.value.issues[0].code == "UNKNOWN_FORMAT"
