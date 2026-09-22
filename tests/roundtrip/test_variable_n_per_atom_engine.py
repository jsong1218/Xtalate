"""Engine honesty for per-atom custom columns that appear in some frames only (v2.0 review, S3).

Post-M72 each ``Frame`` carries its own ``custom_per_atom``, so a per-atom column can legitimately
appear in a later frame that frame 0 lacks — constant-N or not. Two seams silently dropped it:

* **Presence (V4).** ``compute_field_presence`` / ``PresenceAccumulator`` read the per-atom key set
  from frame 0 only, so a later-frame key produced no ``PathPresence`` entry — invisible to the
  Discovery Report, the pre-flight diff, and the completeness invariant.
* **Streamed conversion (V1).** The streaming write plan latched the ``custom_per_atom`` per-key
  refinement from frame 0, so a pattern-writable later-frame key was dropped from every frame with
  no report — while the materialized path (once presence unions) preserves it.

These pin the corrected behaviour: presence unions per-atom keys across all frames, a streamed
conversion preserves (or reports the loss of) a later-frame key exactly as the materialized path
does, and streamed == materialized (the M73 identity theorem).
"""

from __future__ import annotations

import io

from xtalate.conversion.engine import ConversionEngine
from xtalate.parsers.extxyz import ExtxyzParser
from xtalate.registry import default_registry
from xtalate.schema import CanonicalObject, Frame
from xtalate.schema.presence import PresenceAccumulator, compute_field_presence
from xtalate.sdk.streaming import materialize

_LATE_KEY_PATH = "user_metadata.custom_per_atom['extxyz:force']"


def _late_key_extxyz() -> bytes:
    # Two constant-N (N=2) frames; frame 1 introduces a per-atom "force" column frame 0 lacks.
    # extXYZ maps a singular non-canonical column name to custom_per_atom['extxyz:force'] and its
    # writable name pattern (D69) admits it, so a faithful target must keep it.
    return (
        b"2\n"
        b'Properties=species:S:1:pos:R:3 Lattice="10 0 0 0 10 0 0 0 10" pbc="T T T"\n'
        b"H 0 0 0\nH 1 0 0\n"
        b"2\n"
        b'Properties=species:S:1:pos:R:3:force:R:3 Lattice="10 0 0 0 10 0 0 0 10" pbc="T T T"\n'
        b"H 0 0 0 0.5 0 0\nH 1 0 0 -0.5 0 0\n"
    )


def _parsed_late_key() -> CanonicalObject:
    return ExtxyzParser().parse(io.BytesIO(_late_key_extxyz()), filename="t.extxyz").canonical


# --- V4: presence unions per-atom keys across all frames ------------------------------------


def test_presence_unions_custom_per_atom_keys_across_frames() -> None:
    obj = _parsed_late_key()
    assert list(obj.frames[0].custom_per_atom) == []  # frame 0 lacks the key
    assert "extxyz:force" in obj.frames[1].custom_per_atom  # frame 1 introduces it
    presence = compute_field_presence(obj)
    assert presence.status_of(_LATE_KEY_PATH) == "present"


def test_streaming_presence_accumulator_unions_per_atom_keys() -> None:
    # The streaming twin must reach the identical PresenceMap (standing rule 3).
    obj = _parsed_late_key()
    acc = PresenceAccumulator(obj.schema_version)
    acc.observe_header(
        trajectory=obj.trajectory,
        simulation=obj.simulation,
        tags=obj.user_metadata.tags,
        annotations=obj.user_metadata.annotations,
        custom_global=obj.user_metadata.custom_global,
    )
    for frame in obj.frames:
        acc.observe_frame(frame)
    assert acc.result().status_of(_LATE_KEY_PATH) == "present"
    assert acc.result() == compute_field_presence(obj)


# --- V1: a later-frame writable key survives a streamed conversion --------------------------


def _reparse_frames(raw: bytes) -> list[Frame]:
    return ExtxyzParser().parse(io.BytesIO(raw), filename="o.extxyz").canonical.frames


def test_streamed_conversion_keeps_a_later_frame_per_atom_key() -> None:
    engine = ConversionEngine(default_registry())
    out = io.BytesIO()
    engine.convert_stream(
        io.BytesIO(_late_key_extxyz()),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=out,
        source_filename="t.extxyz",
    )
    frames = _reparse_frames(out.getvalue())
    # The later-frame 'force' column must round-trip on frame 1, not vanish.
    assert "extxyz:force" in frames[1].custom_per_atom


def test_streamed_equals_materialized_for_a_later_frame_key() -> None:
    engine = ConversionEngine(default_registry())
    raw = _late_key_extxyz()

    streamed_out = io.BytesIO()
    engine.convert_stream(
        io.BytesIO(raw),
        source_format_id="extxyz",
        target_format_id="extxyz",
        output=streamed_out,
        source_filename="t.extxyz",
    )

    src = ExtxyzParser().parse(io.BytesIO(raw), filename="t.extxyz").canonical
    materialized = engine.convert(
        src, source_format_id="extxyz", target_format_id="extxyz", source_filename="t.extxyz"
    )
    assert streamed_out.getvalue() == materialized.output


def test_streamed_and_materialized_presence_agree_on_the_late_key() -> None:
    # The materialized path must also surface the late key now that presence unions (V4→V1).
    obj = _parsed_late_key()
    streamed_obj, _ = materialize(
        ExtxyzParser().parse_stream(io.BytesIO(_late_key_extxyz()), filename="t.extxyz")
    )
    assert compute_field_presence(obj).status_of(_LATE_KEY_PATH) == "present"
    assert compute_field_presence(streamed_obj).status_of(_LATE_KEY_PATH) == "present"
