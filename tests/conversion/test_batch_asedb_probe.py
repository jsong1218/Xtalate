"""E5: a multi-row ASE .db costs N row decodes in a batch, not 2N, and every report is unchanged."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from ase import Atoms
from ase.db import connect

from xtalate.capabilities import Registry
from xtalate.conversion.batch import BatchManifest, run_batch
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.parsers.ase_db import AseDbParser
from xtalate.sdk import ParseError


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def _db(tmp_path: Path, structures: list[Atoms], name: str = "d.db") -> Path:
    path = tmp_path / name
    db = connect(str(path), use_lock_file=False)
    for atoms in structures:
        db.write(atoms)
    return path


def _co() -> Atoms:
    return Atoms("CO", positions=[[0.0, 0.0, 0.0], [1.13, 0.0, 0.0]])


def _water() -> Atoms:
    return Atoms("H2O", positions=[[0.0, 0.0, 0.0], [0.96, 0.0, 0.0], [0.0, 0.96, 0.0]])


def _spy_select_row(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    decoded: list[int] = []
    real = AseDbParser._select_row

    def spy(self: AseDbParser, db: Any, rid: int) -> Any:
        decoded.append(rid)
        return real(self, db, rid)

    monkeypatch.setattr(AseDbParser, "_select_row", spy)
    return decoded


def test_row_count_is_id_only_and_never_decodes_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db(tmp_path, [_co(), _water(), _co()])
    decoded = _spy_select_row(monkeypatch)
    assert AseDbParser().row_count(io.BytesIO(path.read_bytes())) == 3
    assert decoded == []


def test_row_count_of_a_malformed_file_is_a_parse_error() -> None:
    with pytest.raises(ParseError):
        AseDbParser().row_count(io.BytesIO(b"not a database"))


def test_fanout_decodes_each_row_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db(tmp_path, [_co(), _water(), _co(), _water()])
    decoded = _spy_select_row(monkeypatch)
    report = run_batch(BatchManifest(sources=[str(path)], target="extxyz"), _registry())
    assert report.tallies.converted == 4
    assert len(decoded) == 4  # was 4 (detection) + 4 (per row) = 8


def _scrub(value: Any) -> Any:
    volatile = {
        "report_id",
        "conversion_report_id",
        "created_at",
        "started_at",
        "finished_at",
        "batch_id",
    }
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in volatile}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def test_fanned_reports_are_unchanged_by_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db(tmp_path, [_co(), _water(), _co()])
    manifest = BatchManifest(sources=[str(path)], target="extxyz")
    probed = run_batch(manifest, _registry())
    # Probe reports "not multi-row": the documented fall-through runs the legacy detection parse.
    monkeypatch.setattr(AseDbParser, "row_count", lambda self, stream: 0)
    legacy = run_batch(manifest, _registry())
    assert _scrub(probed.model_dump(mode="json")) == _scrub(legacy.model_dump(mode="json"))


def test_single_row_db_never_fans_out(tmp_path: Path) -> None:
    single = _db(tmp_path, [_co()], "one.db")
    report = run_batch(BatchManifest(sources=[str(single)], target="extxyz"), _registry())
    assert [e.source for e in report.entries] == [str(single)]


def test_a_pinned_row_selection_skips_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _db(tmp_path, [_co(), _water()])
    probed: list[int] = []

    def spy(self: AseDbParser, stream: Any) -> int:
        probed.append(1)
        return 2

    monkeypatch.setattr(AseDbParser, "row_count", spy)
    manifest = BatchManifest(
        sources=[str(path)],
        target="extxyz",
        recovery_choices=["asedb_row_selection=index,row=1"],
    )
    report = run_batch(manifest, _registry())
    assert probed == []
    assert report.tallies.converted == 1
