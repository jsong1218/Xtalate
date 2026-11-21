"""End to end: the H5MD periodicity choice lands in the report as an Assumption + supplied entry."""

from __future__ import annotations

import numpy as np

from tests.parsers.test_h5md import _minimal_h5md
from xtalate.conversion import ConversionEngine
from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.registry import default_registry


def test_periodicity_choice_threads_into_the_conversion_report() -> None:
    reg = default_registry()
    data = _minimal_h5md(
        positions=[np.array([[0.0, 0, 0], [0, 0, 1.0]])],
        species=[np.array([1, 8], dtype=np.int64)],
        box_edges=np.diag([5.0, 6.0, 7.0]),
    ).getvalue()
    pr = parse_with_recovery(
        reg,
        data,
        filename="f.h5md",
        recovery_choices={"ambiguous_periodicity": {"choice": "periodic"}},
    )
    assert [a.scenario for a in pr.assumptions] == ["ambiguous_periodicity"]
    result = ConversionEngine(reg).convert(
        pr.canonical,
        source_format_id=pr.format_id,
        target_format_id="extxyz",
        parse_recovery=pr,
    )
    report = result.report
    assert any(a.scenario == "ambiguous_periodicity" for a in report.assumptions)
    assert any(e.path == "cell.pbc" for e in report.supplied)
