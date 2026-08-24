"""The v2.0 variable-N evidence case for the assemble output mode (v1.5 M54-S2, D203).

The committed ``assembled.extxyz`` is the artifact Xtalate's own assemble mode produced from two
constant-N sources of differing composition. Its single-object re-parse must refuse with the
**existing** ``EXTXYZ_VARIABLE_ATOM_COUNT`` — the same measured refusal the parser enforces for
any one file, reached here at dataset scale. Pinning the refusal (like the wild corpus pins the
LAMMPS deposition case) keeps the evidence counted, not anecdotal: if the assembly ever started
silently padding/truncating frames to fake a re-parseable file, this test fails.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from xtalate.capabilities import Registry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.sdk import ParseError

HERE = Path(__file__).parent
CASE = HERE / "v2-variable-n-assemble"
ASSEMBLED = CASE / "assembled.extxyz"


def _registry() -> Registry:
    reg = Registry()
    for parser in builtin_parsers():
        reg.register_parser(parser)
    for exporter in builtin_exporters():
        reg.register_exporter(exporter)
    return reg


def test_assembled_variable_n_artifact_refuses_single_object_reparse() -> None:
    reg = _registry()
    with pytest.raises(ParseError) as excinfo:
        reg.get_parser("extxyz").parse(io.BytesIO(ASSEMBLED.read_bytes()), filename=ASSEMBLED.name)
    issue = excinfo.value.issues[0]
    assert issue.code == "EXTXYZ_VARIABLE_ATOM_COUNT"
    # The refusal names the first diverging frame and the count it saw (measured, never padded).
    assert "frame 2" in issue.message
    assert "3 atoms" in issue.message or "2 atoms" in issue.message


def test_evidence_manifest_declares_the_expectation() -> None:
    import yaml

    manifest = yaml.safe_load((CASE / "manifest.yaml").read_text())
    assert manifest["case"] == "v2-variable-n-assemble"
    assert manifest["expectation"]["parse_error"] == "EXTXYZ_VARIABLE_ATOM_COUNT"
