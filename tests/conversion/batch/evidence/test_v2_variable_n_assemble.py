"""The v2.0 variable-N evidence case for the assemble output mode (v1.5 M54-S2, D203; M73-S5).

The committed ``assembled.extxyz`` is the artifact Xtalate's own assemble mode produced from two
constant-N sources of differing composition. Before schema 2.0 its single-object re-parse refused
with ``EXTXYZ_VARIABLE_ATOM_COUNT``; since M72 lifted the constant-N invariant and M73-S4 retired
that reader refusal, it now **reads through** as one variable-N Canonical Object — each frame at
its own measured atom count, never padded or truncated. Pinning the read-through (like the wild
corpus pins the LAMMPS deposition case) keeps the evidence counted, not anecdotal: if the assembly
ever started silently padding/truncating frames to force a constant-N file, the measured counts
here would change and this test would fail.
"""

from __future__ import annotations

import io
from pathlib import Path

from xtalate.capabilities import Registry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers

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


def test_assembled_variable_n_artifact_reads_through_as_one_object() -> None:
    reg = _registry()
    obj = (
        reg.get_parser("extxyz")
        .parse(io.BytesIO(ASSEMBLED.read_bytes()), filename=ASSEMBLED.name)
        .canonical
    )
    # The whole file re-parses as one variable-N trajectory: 3-atom frames then a 2-atom frame,
    # each at its own measured count (never padded or truncated to a single N).
    assert [len(f.atoms.symbols) for f in obj.frames] == [3, 3, 2]
    assert len({len(f.atoms.symbols) for f in obj.frames}) == 2  # genuinely variable N


def test_evidence_manifest_declares_the_expectation() -> None:
    import yaml

    manifest = yaml.safe_load((CASE / "manifest.yaml").read_text())
    assert manifest["case"] == "v2-variable-n-assemble"
    assert manifest["expectation"]["frame_counts"] == [3, 3, 2]
