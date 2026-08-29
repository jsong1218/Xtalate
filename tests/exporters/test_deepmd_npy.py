"""DeePMD-kit ``.npy`` system-directory exporter tests (v1.5 M56-S2).

The exporter writes **one Canonical Object → one system directory** (``export_dir`` over an
ordered relative-path → bytes mapping): ``type.raw``/``type_map.raw`` from the species (or
restoring a source-parsed system's carried numbering byte-faithfully), one ``set.000`` (never
a train/test split — aggregation, not curation), labels written only when present, and the
virial inverting S1's pinned mapping **only when both stress and a cell are present** (never
fabricated, P3).
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
from xtalate.exporters.deepmd_npy import make_deepmd_npy_exporter
from xtalate.parsers.deepmd_npy import make_deepmd_npy_parser
from xtalate.schema import CanonicalObject, Cell

EXPORTER = make_deepmd_npy_exporter()
PARSER = make_deepmd_npy_parser()


def _object(files: dict[str, bytes]) -> CanonicalObject:
    return PARSER.parse_dir(files, dirname="system").canonical


def _load(out: dict[str, bytes], path: str) -> np.ndarray:
    return np.asarray(np.load(io.BytesIO(out[path]), allow_pickle=False))


def test_labeled_object_writes_one_set_000_system() -> None:
    source = _object(
        write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT], energy=H2O_ENERGY, forces=[H2O_FORCES])
    )
    out = EXPORTER.export_dir(source)
    # Exactly one set, never a split (v1.5 standing rule 1: DeePMD sharding is curation, which
    # Xtalate refuses to make).
    set_paths = sorted({p.split("/")[0] for p in out if p.startswith("set.")})
    assert set_paths == ["set.000"]
    assert out["type.raw"] == b"0 1 1\n"
    assert out["type_map.raw"] == b"O H\n"
    np.testing.assert_allclose(_load(out, "set.000/coord.npy"), H2O_COORDS.reshape(1, -1))
    np.testing.assert_allclose(_load(out, "set.000/box.npy"), BOX_FLAT.reshape(1, -1))
    np.testing.assert_allclose(_load(out, "set.000/energy.npy"), [-14.0])
    np.testing.assert_allclose(_load(out, "set.000/force.npy"), H2O_FORCES.reshape(1, -1))
    assert "set.000/virial.npy" not in out  # no stress in the source → no virial


def test_carried_type_numbering_restores_byte_faithfully() -> None:
    # A source whose type_map order is NOT first-appearance-collapsed round-trips byte-identically
    # through the carry (D209): the exporter must not renumber, or the re-parse would drift.
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
        type_map=("O", "H"),
        type_indices=(0, 1, 1),
    )
    source = _object(files)
    out = EXPORTER.export_dir(source)
    assert out["type.raw"] == files["type.raw"]
    assert out["type_map.raw"] == files["type_map.raw"]
    # And the re-parse reproduces the same carry, so a deepmd_npy → deepmd_npy conversion
    # validates (absence_conformance) rather than re-deriving a drifted numbering.
    reparse = PARSER.parse_dir(out, dirname="system").canonical
    assert reparse.user_metadata.custom_global == source.user_metadata.custom_global


def test_virial_inverts_the_s1_fixture() -> None:
    # The S2 go/no-go: stress diag(0.01, 0.02, 0.03) eV/Å³ against the 1000 Å³ box writes
    # virial = [-10, 0, 0, 0, -20, 0, 0, 0, -30] — exactly the S1 fixture's bytes.
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
        virial=[VIRIAL_FLAT],
    )
    source = _object(files)
    out = EXPORTER.export_dir(source)
    np.testing.assert_allclose(_load(out, "set.000/virial.npy"), VIRIAL_FLAT.reshape(1, -1))
    # Round-trip: the written virial re-parses back to the same stress.
    reparse = PARSER.parse_dir(out, dirname="system").canonical
    assert reparse.frames[0].electronic.stress is not None
    np.testing.assert_allclose(
        reparse.frames[0].electronic.stress, np.diag([0.01, 0.02, 0.03]), atol=1e-12
    )


def test_stress_without_a_cell_writes_no_virial() -> None:
    # P3 — never fabricated: a stress with no cell cannot become a virial, so virial is simply
    # absent (the ordinary capability-matrix prediction), never invented.
    files = write_system(
        coords=[H2O_COORDS],
        boxes=[BOX_FLAT],
        energy=H2O_ENERGY,
        forces=[H2O_FORCES],
        virial=[VIRIAL_FLAT],
    )
    obj = _object(files).model_copy(
        update={
            "frames": [frame.model_copy(update={"cell": None}) for frame in _object(files).frames]
        }
    )
    out = EXPORTER.export_dir(obj)
    assert "set.000/virial.npy" not in out


def test_absent_labels_write_no_label_files() -> None:
    obj = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT]))
    out = EXPORTER.export_dir(obj)
    assert not any(p.endswith(("energy.npy", "force.npy", "virial.npy")) for p in out)


def test_multi_frame_object_writes_one_set_with_all_frames() -> None:
    files = write_system(
        coords=[H2O_COORDS, H2O_COORDS + 0.1],
        boxes=[BOX_FLAT, BOX_FLAT],
        energy=[-14.0, -14.1],
        forces=[H2O_FORCES, H2O_FORCES],
    )
    out = EXPORTER.export_dir(_object(files))
    assert sorted({p.split("/")[0] for p in out if p.startswith("set.")}) == ["set.000"]
    coords = _load(out, "set.000/coord.npy")
    assert coords.shape == (2, 9)


def test_zero_box_cell_is_written_back_as_zero_box() -> None:
    # cell None → the DeePMD nopbc marker (all-zero box), round-tripping the S1 read rule.
    obj = _object(write_system(coords=[H2O_COORDS], boxes=[np.zeros(9)]))
    out = EXPORTER.export_dir(obj)
    np.testing.assert_allclose(_load(out, "set.000/box.npy"), np.zeros((1, 9)))


def test_fixed_composition_and_order_are_enforced() -> None:
    files_a = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])
    files_b = write_system(
        coords=[H2O_COORDS], boxes=[BOX_FLAT], type_map=("H", "O"), type_indices=(0, 1, 0)
    )
    obj_a = _object(files_a)
    obj_b = _object(files_b)  # same composition, different atom order (H, O, H)
    assert obj_a.frames[0].atoms.symbols == ["O", "H", "H"]
    assert obj_b.frames[0].atoms.symbols == ["H", "O", "H"]
    merged = obj_a.model_copy(update={"frames": [obj_a.frames[0], obj_b.frames[0]]})
    with pytest.raises(ValueError, match="fixed composition"):
        EXPORTER.export_dir(merged)


def test_empty_object_refuses() -> None:
    obj = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT]))
    with pytest.raises(ValueError, match="empty"):
        EXPORTER.export_dir(obj.model_copy(update={"frames": []}))


def test_unrepresentable_reports_varying_composition_and_empty() -> None:
    # `unrepresentable` is the clean-refusal gate (D179): the engine consults it *before*
    # `export_dir`, so a value-level constraint becomes a refused report, never a mid-write crash.
    good = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT]))
    assert EXPORTER.unrepresentable(good) is None
    files_b = write_system(
        coords=[H2O_COORDS], boxes=[BOX_FLAT], type_map=("H", "O"), type_indices=(0, 1, 0)
    )
    varying = good.model_copy(update={"frames": [good.frames[0], _object(files_b).frames[0]]})
    assert "composition or order" in (EXPORTER.unrepresentable(varying) or "")
    assert "empty" in (EXPORTER.unrepresentable(good.model_copy(update={"frames": []})) or "")


def _degenerate_stress_object() -> CanonicalObject:
    # A schema-legal object (DPMD-2): a non-zero but singular (zero-volume) lattice paired with a
    # stress — the schema's Cell has no non-degenerate validator for lattice-vector-native
    # formats, so nothing upstream stops this object from reaching the exporter.
    good = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT], virial=[VIRIAL_FLAT]))
    return good.model_copy(
        update={
            "frames": [
                frame.model_copy(
                    update={
                        "cell": Cell(
                            lattice_vectors=np.array(
                                [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
                            ),
                            pbc=(True, True, True),
                        )
                    }
                )
                for frame in good.frames
            ]
        }
    )


def test_degenerate_cell_with_stress_refuses_via_unrepresentable() -> None:
    # DPMD-2: the clean-refusal gate must catch a degenerate-cell-plus-stress object ahead of
    # export_dir, which would otherwise crash in virial_from_stress on volume ≤ 0.
    good = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT], virial=[VIRIAL_FLAT]))
    assert EXPORTER.unrepresentable(good) is None
    message = EXPORTER.unrepresentable(_degenerate_stress_object())
    assert message is not None
    assert "degenerate" in message and "frame 0" in message


def test_degenerate_cell_with_stress_refuses_cleanly_through_engine() -> None:
    # The crash-to-refusal contract end-to-end: the conversion is a completed *refused* report
    # (UNREPRESENTABLE_VALUE), never a raw ValueError escaping the engine.
    from xtalate.conversion import ConversionEngine
    from xtalate.registry import default_registry

    result = ConversionEngine(default_registry()).convert(
        _degenerate_stress_object(), source_format_id="extxyz", target_format_id="deepmd_npy"
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "UNREPRESENTABLE_VALUE"


def test_varying_composition_refuses_cleanly_through_engine() -> None:
    # A schema-legal trajectory (constant atom *count*, differing per-atom symbols) converted to
    # deepmd_npy must be a completed *refused* report, not a raw ValueError escaping the engine.
    from xtalate.conversion import ConversionEngine
    from xtalate.registry import default_registry

    good = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT]))
    files_b = write_system(
        coords=[H2O_COORDS], boxes=[BOX_FLAT], type_map=("H", "O"), type_indices=(0, 1, 0)
    )
    second = _object(files_b).frames[0].model_copy(update={"index": 1})
    varying = good.model_copy(update={"frames": [good.frames[0], second]})
    result = ConversionEngine(default_registry()).convert(
        varying, source_format_id="extxyz", target_format_id="deepmd_npy"
    )
    assert result.report.status == "refused"
    assert result.report.refusal is not None
    assert result.report.refusal["code"] == "UNREPRESENTABLE_VALUE"


def test_stream_export_refuses_a_directory_is_not_a_stream() -> None:
    obj = _object(write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT]))
    with pytest.raises(NotImplementedError, match="directory format"):
        EXPORTER.export(obj, io.BytesIO())


def test_assemble_dir_groups_by_exact_composition_and_order() -> None:
    from xtalate.sdk import AssembleContribution

    water = _object(
        write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT], energy=H2O_ENERGY, forces=[H2O_FORCES])
    )
    water2 = _object(
        write_system(
            coords=[H2O_COORDS + 0.2], boxes=[BOX_FLAT], energy=H2O_ENERGY, forces=[H2O_FORCES]
        )
    )
    co = _object(
        write_system(
            coords=[[[0, 0, 0], [0, 0, 1.1]]],
            boxes=[BOX_FLAT],
            type_map=("C", "O"),
            type_indices=(0, 1),
        )
    )
    contributions = [
        AssembleContribution(canonical=water, output=[b""]),
        AssembleContribution(canonical=co, output=[b""]),
        AssembleContribution(canonical=water2, output=[b""]),
    ]
    out, systems = EXPORTER.assemble_dir(contributions)
    # Two composition groups, deterministic by first appearance: system_000 = the two H2O
    # sources' frames merged into one system; system_001 = the CO source.
    assert sorted({p.split("/", 1)[0] for p in out}) == ["system_000", "system_001"]
    # The ordered source→system assignment is index-aligned with the contributions: both water
    # sources → system_000, the CO source → system_001 (the mapping the batch aggregate records).
    assert systems == ["system_000", "system_001", "system_000"]
    coords0 = _load(out, "system_000/set.000/coord.npy")
    assert coords0.shape == (2, 9)  # both water frames merged into one system's set.000
    assert out["system_000/type.raw"] == b"0 1 1\n"
    assert out["system_001/type.raw"] == b"0 1\n"
    assert out["system_001/type_map.raw"] == b"C O\n"


def test_assemble_dir_refuses_an_order_mismatch_as_separate_systems() -> None:
    # Two contributions with the same composition but different atom *order* cannot share one
    # DeePMD system (type.raw is per-atom) — they become separate systems, never a silent
    # reorder (identity atom_permutation).
    from xtalate.sdk import AssembleContribution

    files_a = write_system(coords=[H2O_COORDS], boxes=[BOX_FLAT])
    files_b = write_system(
        coords=[H2O_COORDS], boxes=[BOX_FLAT], type_map=("H", "O"), type_indices=(0, 1, 0)
    )
    contributions = [
        AssembleContribution(canonical=_object(files_a), output=[b""]),
        AssembleContribution(canonical=_object(files_b), output=[b""]),
    ]
    out, systems = EXPORTER.assemble_dir(contributions)
    assert sorted({p.split("/", 1)[0] for p in out}) == ["system_000", "system_001"]
    assert systems == ["system_000", "system_001"]
