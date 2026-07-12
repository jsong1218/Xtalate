"""Canonical-path authority and wildcard expansion (Part 2 §3 / Part 3 §4.1)."""

from __future__ import annotations

import pytest

from xtalate.schema.paths import (
    CANONICAL_FIELD_PATHS,
    expand_capability_path,
    is_valid_path,
)


def test_known_scientific_paths_are_valid() -> None:
    for path in [
        "atoms.symbols",
        "atoms.positions",
        "cell.lattice_vectors",
        "cell.pbc",
        "dynamics.velocities",
        "electronic.total_energy",
        "electronic.total_spin",
        "frame.time",
        "trajectory.timestep",
        "user_metadata.custom_per_atom",
        "user_metadata.custom_per_frame",
    ]:
        assert is_valid_path(path), path


def test_unknown_path_is_invalid() -> None:
    assert not is_valid_path("dynamics.spins")
    assert not is_valid_path("atoms.charge")  # charges live under electronic


def test_expand_plain_path_returns_itself() -> None:
    assert expand_capability_path("dynamics.velocities") == ["dynamics.velocities"]


def test_expand_unknown_path_raises() -> None:
    with pytest.raises(ValueError, match="unknown canonical field path"):
        expand_capability_path("simulation.nonexistent")


def test_wildcard_expands_to_all_leaves_under_prefix() -> None:
    expanded = expand_capability_path("simulation.*")
    assert "simulation.xc_functional" in expanded
    assert "simulation.extra" in expanded
    assert all(p.startswith("simulation.") for p in expanded)
    # every expanded leaf is itself a valid concrete path
    assert set(expanded) <= CANONICAL_FIELD_PATHS


def test_frame_wildcard_expands_to_frame_time() -> None:
    assert expand_capability_path("frame.*") == ["frame.time"]


def test_unknown_wildcard_prefix_raises() -> None:
    with pytest.raises(ValueError, match="unknown capability wildcard prefix"):
        expand_capability_path("bogus.*")
