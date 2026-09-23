"""Contract + honesty tests for the composition/density reference plugin (M69).

Built only on the public surface — ``run_analysis`` and constructed ``CanonicalObject``s, exactly
how a third party tests their own plugin — so this file is also part of the docs' worked example.
"""

from __future__ import annotations

import numpy as np
import pytest
from xtalate_analysis_composition.analysis import (
    CompositionAnalysis,
    element_counts,
    hill_formula,
)

from xtalate.schema import AtomsBlock, CanonicalObject, Cell, Frame, Provenance
from xtalate.sdk.analysis import run_analysis


def _water(*, cell: bool, masses: bool) -> CanonicalObject:
    """A water monomer, optionally in a 10 Å cubic cell, optionally with explicit masses (u)."""
    atoms = AtomsBlock(
        symbols=["O", "H", "H"],
        positions=np.array([[0.0, 0.0, 0.0], [0.96, 0.0, 0.0], [-0.24, 0.93, 0.0]]),
        masses=np.array([15.999, 1.008, 1.008]) if masses else None,
    )
    frame = Frame(
        index=0,
        atoms=atoms,
        cell=Cell(lattice_vectors=np.eye(3) * 10.0, pbc=(True, True, True)) if cell else None,
    )
    return CanonicalObject(
        frames=[frame],
        provenance=Provenance(
            source_filename="water.xyz",
            source_format="xyz",
            original_coordinate_system="cartesian",
        ),
    )


def test_element_counts_tallies_symbols() -> None:
    assert element_counts(["O", "H", "H"]) == {"O": 1, "H": 2}


def test_hill_formula_water_no_carbon_is_alphabetical() -> None:
    # No carbon: every element alphabetical, H included. Count 1 is omitted.
    assert hill_formula({"O": 1, "H": 2}) == "H2O"


def test_hill_formula_with_carbon_puts_c_then_h_then_rest() -> None:
    # Ethanol C2H6O: carbon first, hydrogen second, then the rest alphabetical.
    assert hill_formula({"H": 6, "O": 1, "C": 2}) == "C2H6O"


def test_analyze_reports_composition_and_density_when_cell_and_masses_exist() -> None:
    result = CompositionAnalysis().analyze(_water(cell=True, masses=True))
    assert result["composition:formula"] == "H2O"
    assert result["composition:element_counts"] == {"O": 1, "H": 2}
    assert result["composition:atom_count"] == 3
    expected = (15.999 + 1.008 + 1.008) / 1000.0 * 1.66053906660
    assert result["composition:mass_density_g_per_cm3"] == pytest.approx(expected, rel=1e-12)
    assert result["composition:density_note"] == (
        "mass density computed on frame 0 from total atomic mass / cell volume"
    )


def test_no_cell_gives_no_density_with_stated_reason() -> None:
    result = CompositionAnalysis().analyze(_water(cell=False, masses=True))
    assert result["composition:mass_density_g_per_cm3"] is None
    assert result["composition:density_note"] == (
        "mass density not computed: no simulation cell declared in the source"
    )
    # Composition is still reported — absence of one field never suppresses the others.
    assert result["composition:formula"] == "H2O"


def test_no_masses_gives_no_density_and_never_fills_them() -> None:
    result = CompositionAnalysis().analyze(_water(cell=True, masses=False))
    assert result["composition:mass_density_g_per_cm3"] is None
    assert "never fills them" in result["composition:density_note"]
    assert "P4" in result["composition:density_note"]


def test_every_returned_key_is_in_the_plugins_namespace() -> None:
    result = CompositionAnalysis().analyze(_water(cell=True, masses=True))
    assert all(key.startswith("composition:") for key in result)


def test_run_analysis_merges_namespace_and_appends_analyze_record() -> None:
    source = _water(cell=True, masses=True)
    annotated = run_analysis(source, CompositionAnalysis()).canonical

    # The plugin's keys land under custom_global; nothing else in user_metadata is touched.
    cg = annotated.user_metadata.custom_global
    assert cg["composition:formula"] == "H2O"
    assert cg["composition:atom_count"] == 3

    # Provenance records who wrote what (D269): one appended analyze record naming the plugin.
    record = annotated.provenance.history[-1]
    assert record.operation == "analyze"
    assert record.parser_version == "composition 1.0.0"

    # The source object is never mutated (the runner hands the plugin a deep copy).
    assert source.user_metadata.custom_global == {}


def _single_frame_note_source() -> CanonicalObject:
    return _water(cell=True, masses=True)


def _variable_n_source() -> CanonicalObject:
    """Two frames with different atom content (variable N, schema 2.0.0): frame 0 is water,
    frame 1 gains an extra hydrogen."""
    f0 = Frame(
        index=0,
        atoms=AtomsBlock(symbols=["O", "H", "H"], positions=np.zeros((3, 3))),
    )
    f1 = Frame(
        index=1,
        atoms=AtomsBlock(symbols=["O", "H", "H", "H"], positions=np.zeros((4, 3))),
    )
    return CanonicalObject(
        frames=[f0, f1],
        provenance=Provenance(
            source_filename="traj.h5",
            source_format="h5md",
            original_coordinate_system="cartesian",
        ),
    )


def test_frames_note_states_single_frame_scope() -> None:
    result = CompositionAnalysis().analyze(_single_frame_note_source())
    assert result["composition:frames_note"] == "computed on the single frame in the source"


def test_frames_note_warns_when_atoms_vary_across_frames() -> None:
    """Under variable N the frame-0 figures are representative, not universal — the note says so
    in plain language rather than letting a caller assume the whole trajectory (P1)."""
    result = CompositionAnalysis().analyze(_variable_n_source())
    note = result["composition:frames_note"]
    assert isinstance(note, str)
    assert "variable N" in note and "frame 0" in note
    # The reported figures are frame 0's water composition, unaffected by the differing frame 1.
    assert result["composition:formula"] == "H2O"
    assert result["composition:atom_count"] == 3
