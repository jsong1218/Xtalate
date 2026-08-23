"""QE pw.x input identity round-trips (v1.4 M51-S2, D194; Part 3 §3): ``input → Canonical →
input' → Canonical'``. This is the proof that M51-S1's exporter and M50's parser agree — the
checkpoint that closes the staging state and makes ``qe_pw_in`` a full read+write format.

The ``carry-kpoints`` golden (M50-S3) is the dedicated identity fixture: it carries masses +
pseudopotentials + a ``K_POINTS`` card + a carried namelist entry (``nspin``) + recognized
simulation context (``ecutwfc``/``ecutrho``/``calculation``/``conv_thr``/``smearing``/
``occupations``) — everything a runnable pw.x input needs — so the round-trip is a **clean
scientific identity** (bare ``assert_scientifically_equal``) and emits **no**
``QEIN_INCOMPLETE_INPUT``: the carry-back covered every run-required entry (D193).

Two routes, mirroring the lammps_data round-trip suite's split:

* **The format-level identity drives the exporter directly** on the full parsed object — the
  object exactly as the parser produced it. This is the S2 "done means" claim: input → canonical →
  input reproduces structure, species, masses, and the carried pseudopotential / ``K_POINTS`` /
  namelist payloads within tolerance, with no incompleteness warning. It bypasses the engine's
  write-plan filter deliberately: the write side declares ``simulation.*`` NONE (D192 rejected
  alternative (d)) so the engine path removes foreign/context metadata and reports it — that is
  the *engine's* honest accounting for cross-format hops, not a statement about what the format
  can hold. The format itself demonstrably round-trips everything, and the exporter's own
  ``export_warnings`` confirms the complete input is complete.
* **The engine path (``qe_pw_in → qe_pw_in``) exercises the real pipeline** on the same golden:
  the four writable QE carry keys survive the write plan and the re-parse reproduces them, the
  conversion completes and validates (the re-parse re-reports the carried entries as warnings, so
  validation is ``passed_with_warnings`` — R4), and the engine honestly drops ``simulation.*`` so
  ``QEIN_INCOMPLETE_INPUT`` fires naming the cutoff — the report telling the truth about exactly
  what was and was not written.
"""

from __future__ import annotations

import io
from pathlib import Path

from tests._format_helpers import assert_scientifically_equal
from xtalate.conversion import ConversionEngine
from xtalate.exporters.qe_pw_in import make_qe_pw_in_exporter
from xtalate.parsers.qe_pw_in import make_qe_pw_in_parser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject, load_canonical

GOLDEN = Path(__file__).parent.parent / "golden" / "qe_pw_in" / "carry-kpoints"

_INCOMPLETE = "QEIN_INCOMPLETE_INPUT"


def _load_source() -> CanonicalObject:
    return load_canonical((GOLDEN / "expected.canonical.json").read_text())


def test_qe_pw_in_identity_round_trip_is_clean_and_warning_free() -> None:
    """``input → Canonical → input' → Canonical'`` is an exact scientific identity for the
    complete QE golden — structure, species, masses, the carried pseudopotential / ``K_POINTS`` /
    namelist payloads, and the recognized simulation context all survive — and because the source
    is complete, the exporter reports **no** ``QEIN_INCOMPLETE_INPUT`` (the carry-back covered
    every run-required entry)."""
    source = _load_source()
    exporter = make_qe_pw_in_exporter()

    # A complete QE input is not incomplete: no QEIN_INCOMPLETE_INPUT.
    assert exporter.export_warnings(source) == []

    written = io.BytesIO()
    exporter.export(source, written)
    roundtrip = (
        make_qe_pw_in_parser().parse(io.BytesIO(written.getvalue()), filename=None).canonical
    )
    assert_scientifically_equal(source, roundtrip)


def test_engine_path_round_trip_preserves_the_carried_payloads() -> None:
    """Through the real Conversion Engine (``qe_pw_in → qe_pw_in``): the four writable QE carry
    keys survive the write plan and re-parse back; the conversion completes and validates; and
    the engine's honest accounting is visible — ``simulation.*`` is NONE on write (D192 rejected
    alternative (d)), so the drop of the cutoff context is *reported* via QEIN_INCOMPLETE_INPUT
    rather than silently written or silently lost."""
    source = _load_source()
    result = ConversionEngine(default_registry()).convert(
        source,
        source_format_id="qe_pw_in",
        target_format_id="qe_pw_in",
    )
    assert result.report.status == "completed"
    assert result.output is not None
    text = result.output.decode("utf-8")
    # The writable carries survive the write plan (the pre-flight predicts no loss for
    # qe_pw_in → qe_pw_in): pseudos, the K_POINTS card, and the carried &system entry.
    assert "fe.pbe.UPF" in text and "o.pbe.UPF" in text
    assert "K_POINTS automatic" in text
    assert "nspin = 2" in text
    # The engine drops simulation.* (foreign/context metadata is reported removed, never
    # borrowed), so the written file has no cutoff — and the report says so in plain language.
    assert "ecutwfc" not in text
    codes = [w.code for w in result.report.warnings if w.source == "export"]
    assert _INCOMPLETE in codes
    assert any("ecutwfc" in w.message for w in result.report.warnings if w.source == "export")
    # The re-parse re-reports the carried entries (QEIN_UNMAPPED_ENTRY_CARRIED) — the R4
    # discipline: a re-parse that succeeded only with warnings is passed_with_warnings, never a
    # clean passed — and the diff checks themselves pass.
    assert result.validation is not None
    assert result.validation.status == "passed_with_warnings"
    problems = [c.status for c in result.validation.checks if c.status not in ("pass", "skipped")]
    assert problems == []
