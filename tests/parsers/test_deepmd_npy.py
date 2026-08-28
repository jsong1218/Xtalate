"""DeePMD-kit ``.npy`` system-directory parser tests (v1.5 M56-S1).

The parser reads **one DeePMD system directory → one Canonical Object** through the
directory-format read seam (``parse_dir`` over an ordered relative-path → bytes mapping).
These tests pin the read contract: ``type_map.raw`` → species (absent → the existing
``missing_species`` recovery), multiple ``set.*`` concatenated in sorted order with the
dropped partition *reported*, absent labels stay ``None`` (never zero-filled, P3), shape
mismatches refuse loudly, a pickled/object ``.npy`` refuses under ``allow_pickle=False``
(an RCE vector, never unpickled), and the virial→stress mapping matches the hand fixture.
"""

from __future__ import annotations

import io

import numpy as np
import pytest

from tests.golden.deepmd_npy._systems import (
    BOX_FLAT,
    H2O_COORDS,
    H2O_ENERGY,
    H2O_FORCES,
    VIRIAL_FLAT,
    write_system,
)
from xtalate.parsers.deepmd_npy import make_deepmd_npy_parser
from xtalate.sdk import ParseError, ParseResult

PARSER = make_deepmd_npy_parser()

_SYSTEM = write_system(
    coords=[H2O_COORDS],
    boxes=[BOX_FLAT],
    energy=H2O_ENERGY,
    forces=[H2O_FORCES],
)


def _parse(files: dict[str, bytes], *, dirname: str = "system") -> ParseResult:
    return PARSER.parse_dir(files, dirname=dirname)


def _error(files: dict[str, bytes]) -> ParseError:
    with pytest.raises(ParseError) as excinfo:
        _parse(files)
    return excinfo.value


def test_labeled_system_parses_to_one_object_with_carried_numbering() -> None:
    result = _parse(_SYSTEM)
    obj = result.canonical
    assert len(obj.frames) == 1
    frame = obj.frames[0]
    assert frame.atoms.symbols == ["O", "H", "H"]
    assert frame.cell is not None
    assert frame.cell.pbc == (True, True, True)
    assert frame.electronic.total_energy == -14.0
    assert frame.dynamics.forces is not None
    np.testing.assert_allclose(frame.dynamics.forces, H2O_FORCES)
    assert frame.electronic.stress is None  # no virial.npy → stress absent, never zero (P3)
    # The source numbering carries verbatim (the exporter's byte-faithful inverse needs both).
    assert obj.user_metadata.custom_global["deepmd_npy:type_map"] == ["O", "H"]
    assert obj.user_metadata.custom_global["deepmd_npy:type_indices"] == [0, 1, 1]
    assert obj.trajectory is None  # one frame → one structure, never a trajectory


def test_multi_frame_system_is_a_trajectory() -> None:
    files = write_system(
        coords=[H2O_COORDS, H2O_COORDS + 0.1],
        boxes=[BOX_FLAT, BOX_FLAT],
        energy=[-14.0, -14.1],
        forces=[H2O_FORCES, H2O_FORCES],
    )
    obj = _parse(files).canonical
    assert len(obj.frames) == 2
    assert obj.trajectory is not None


def test_missing_label_files_are_absent_not_zero_filled() -> None:
    bare = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])
    frame = _parse(bare).canonical.frames[0]
    assert frame.electronic.total_energy is None
    assert frame.dynamics.forces is None
    assert frame.electronic.stress is None


def test_zero_box_means_no_cell() -> None:
    # DeePMD's nopbc marker is an all-zero box: it maps to cell None (a real cell is never the
    # zero matrix, so absence is unambiguous) — audited against DeePMD's docs at M56-S1.
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[np.zeros(9, dtype=np.float64)],
        energy=H2O_ENERGY,
    )
    frame = _parse(files).canonical.frames[0]
    assert frame.cell is None


def test_multi_set_concatenates_in_sorted_order_and_reports_the_dropped_partition() -> None:
    files = write_system(
        coords=[
            H2O_COORDS,
            H2O_COORDS + np.array([0.05, 0.0, 0.0]),
            H2O_COORDS + np.array([0.0, 0.05, 0.0]),
        ],
        boxes=[BOX_FLAT, BOX_FLAT, BOX_FLAT],
        energy=[-14.0, -14.05, -14.1],
        forces=[H2O_FORCES, H2O_FORCES + 0.01, H2O_FORCES - 0.01],
        set_splits=[2, 1],  # set.000 (2 frames) then set.001 (1 frame)
    )
    result = _parse(files)
    assert len(result.canonical.frames) == 3
    # Frames concatenated in sorted set order: frame 1 is set.001's frame.
    np.testing.assert_allclose(
        result.canonical.frames[2].atoms.positions,
        H2O_COORDS + np.array([0.0, 0.05, 0.0]),
    )
    codes = [issue.code for issue in result.issues]
    # The partition is information, so its loss is announced — never silent.
    assert "DEEPMD_SET_PARTITION_DROPPED" in codes


def test_per_set_atom_count_mismatch_refuses_inconsistent_shapes() -> None:
    # DPMD-1: set.001 carries a different atom count than set.000 (4 vs 3), so the concatenate
    # would raise a raw ValueError before _validate_array runs. It must surface as the
    # DEEPMD_INCONSISTENT_SHAPES refusal naming the offending set and its shape.
    files = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])
    files["set.001/coord.npy"] = np_save(np.zeros((1, 12), dtype=np.float64))
    files["set.001/box.npy"] = np_save(np.zeros((1, 9), dtype=np.float64))
    error = _error(files)
    assert error.issues[0].code == "DEEPMD_INCONSISTENT_SHAPES"
    message = error.issues[0].message
    assert "set.001" in message and "(1, 12)" in message


def test_virial_maps_to_hand_computed_stress() -> None:
    # The S1 go/no-go: virial = -stress·volume for the hand fixture (D211, the recorded mapping).
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
        virial=[VIRIAL_FLAT],
    )
    stress = _parse(files).canonical.frames[0].electronic.stress
    assert stress is not None
    np.testing.assert_allclose(stress, np.diag([0.01, 0.02, 0.03]), atol=1e-12)


def test_missing_type_map_refuses_recoverable_and_resolves_via_species_map() -> None:
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
        omit_type_map=True,
    )
    error = _error(files)
    assert error.issues[0].code == "DEEPMD_MISSING_TYPE_MAP"
    assert error.issues[0].recovery_hint == "supply_species"
    recovered = PARSER.parse_recover(
        b"",
        filename="system",
        hint="supply_species",
        choice="species_map",
        parameters={"species": "O H", "directory_files": files},
        recovery_context={},
    )
    assert recovered.canonical.frames[0].atoms.symbols == ["O", "H", "H"]
    # The applied species is the only parameter the choice records (the whitelist pin of D209:
    # the directory payload rides the recovery channel, never the recorded Assumption).
    assert recovered.canonical.user_metadata.custom_global["deepmd_npy:type_map"] == ["O", "H"]


def test_type_raw_must_be_integer_indices() -> None:
    files = dict(_SYSTEM)
    files["type.raw"] = b"O H H\n"
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"


def test_type_index_out_of_range_refuses() -> None:
    files = dict(_SYSTEM)
    files["type.raw"] = b"0 1 5\n"
    assert _error(files).issues[0].code == "DEEPMD_INCONSISTENT_SHAPES"


def test_invalid_type_map_symbol_refuses() -> None:
    files = dict(_SYSTEM)
    files["type_map.raw"] = b"O Xx\n"
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"


def test_missing_required_file_refuses_malformed_layout() -> None:
    files = dict(_SYSTEM)
    del files["type.raw"]
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"
    files = dict(_SYSTEM)
    del files["set.000/coord.npy"]
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"
    files = dict(_SYSTEM)
    del files["set.000/box.npy"]
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"


def test_shape_mismatches_refuse_inconsistent_shapes() -> None:
    # coord.npy frame count disagrees with box.npy.
    files = dict(_SYSTEM)
    files["set.000/box.npy"] = np_save(np.zeros((2, 9), dtype=np.float64))
    assert _error(files).issues[0].code == "DEEPMD_INCONSISTENT_SHAPES"
    # force.npy flat size disagrees with 3·n_atoms.
    files = dict(_SYSTEM)
    files["set.000/force.npy"] = np_save(np.zeros((1, 4), dtype=np.float64))
    assert _error(files).issues[0].code == "DEEPMD_INCONSISTENT_SHAPES"
    # coord flat size not divisible by 3.
    files = dict(_SYSTEM)
    files["set.000/coord.npy"] = np_save(np.zeros((1, 5), dtype=np.float64))
    assert _error(files).issues[0].code == "DEEPMD_INCONSISTENT_SHAPES"


def test_pickled_object_array_refuses_never_unpickles() -> None:
    # A pickled .npy is an RCE vector: numpy.load(..., allow_pickle=False) must refuse it as
    # DEEPMD_MALFORMED_LAYOUT — the bytes are never deserialized.
    stream = io.BytesIO()
    np.save(stream, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    files = dict(_SYSTEM)
    files["set.000/coord.npy"] = stream.getvalue()
    assert _error(files).issues[0].code == "DEEPMD_MALFORMED_LAYOUT"


def test_zero_frames_refuses_empty() -> None:
    files = dict(_SYSTEM)
    files["set.000/coord.npy"] = np_save(np.zeros((0, 9), dtype=np.float64))
    files["set.000/box.npy"] = np_save(np.zeros((0, 9), dtype=np.float64))
    assert _error(files).issues[0].code == "DEEPMD_EMPTY"


def test_stream_parse_refuses_a_directory_is_not_a_file() -> None:
    with pytest.raises(ParseError) as excinfo:
        PARSER.parse(io.BytesIO(b"not a deepmd system"), filename="system")
    assert excinfo.value.issues[0].code == "DEEPMD_MALFORMED_LAYOUT"


def test_sniff_never_matches_a_file_head() -> None:
    # A DeePMD system is a directory; a file head is never one (hints come from the listing).
    assert PARSER.sniff(b"type.raw", "system") == 0.0


def test_sniff_dir_scores_the_listing() -> None:
    entries = sorted(_SYSTEM)
    assert PARSER.sniff_dir(entries, "system") == 1.0
    assert PARSER.sniff_dir(["type.raw", "set.000/coord.npy"], "system") == 0.35
    assert PARSER.sniff_dir(["random.txt"], "system") == 0.0


def np_save(value: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, value, allow_pickle=False)
    return stream.getvalue()
