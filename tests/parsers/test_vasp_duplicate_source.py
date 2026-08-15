"""The duplicate-source policy (v1.2 M44-S3): Xtalate converts the file it is *given*, never a
sibling.

VASP writes an OUTCAR log and a vasprun.xml side by side for the same run, and both parsers are
registered. The contract is that Xtalate converts the **one** file the caller named — it never
cross-reads the sibling. Silent multi-file assembly would be *undeclared input* (P1's litmus test):
a user diffing the single file they named against the output would be surprised by values that came
from a file they never named.

**Rejected alternative (recorded here, D170):** *cross-file reconciliation* — assembling one
canonical object from an OUTCAR **and** its vasprun.xml together — as undeclared multi-file input;
a future *explicit, opt-in* reconciliation of two named files is the honest seam, never an implicit
parser behavior.

The test writes a deliberately **different-content** sibling (the per-step energies differ by
+10 eV)
into the same directory, hands the parser the named file's own bytes with its real on-disk
``filename`` (so a hypothetical cross-reading parser *could* locate the sibling), and asserts each
parser returns its **own** file's values — never the sibling's.
"""

from __future__ import annotations

import dataclasses
import io
from pathlib import Path

import pytest

from tests.parsers._vasp_run import H2O_RUN, render_outcar, render_vasprun
from xtalate.parsers.outcar import make_outcar_parser
from xtalate.parsers.vasprun import make_vasprun_parser


def _vasprun_with_different_energies() -> str:
    """The same run, re-rendered as vasprun.xml with every per-step energy shifted +10 eV — the
    deliberately different content that a cross-reading parser would leak into the OUTCAR result."""
    steps = [dataclasses.replace(s, energy=s.energy + 10.0) for s in H2O_RUN.steps]
    return render_vasprun(dataclasses.replace(H2O_RUN, steps=steps))


def _energies(obj: object) -> list[float]:
    return [f.electronic.total_energy for f in obj.frames]  # type: ignore[attr-defined]


def test_parsing_outcar_is_unaffected_by_a_different_content_vasprun_sibling(
    tmp_path: Path,
) -> None:
    """An OUTCAR parses to its own energies even when a different-content vasprun.xml sits
    beside it."""
    outcar_text = render_outcar(H2O_RUN)
    (tmp_path / "OUTCAR").write_text(outcar_text, encoding="utf-8")
    (tmp_path / "vasprun.xml").write_text(_vasprun_with_different_energies(), encoding="utf-8")

    parsed = (
        make_outcar_parser()
        .parse(io.BytesIO(outcar_text.encode()), filename=str(tmp_path / "OUTCAR"))
        .canonical
    )

    # The OUTCAR's own energies — not the sibling vasprun's (which are +10 eV, i.e. -66.4 …).
    assert _energies(parsed) == pytest.approx([-76.4, -76.41, -76.42])


def test_parsing_vasprun_is_unaffected_by_a_different_content_outcar_sibling(
    tmp_path: Path,
) -> None:
    """The symmetric case: a vasprun.xml parses to its own energies beside a
    different-content OUTCAR."""
    vasprun_text = _vasprun_with_different_energies()
    (tmp_path / "vasprun.xml").write_text(vasprun_text, encoding="utf-8")
    (tmp_path / "OUTCAR").write_text(render_outcar(H2O_RUN), encoding="utf-8")

    parsed = (
        make_vasprun_parser()
        .parse(io.BytesIO(vasprun_text.encode()), filename=str(tmp_path / "vasprun.xml"))
        .canonical
    )

    # The vasprun's own (+10 eV) energies — not the OUTCAR sibling's (-76.4 …).
    assert _energies(parsed) == pytest.approx([-66.4, -66.41, -66.42])
