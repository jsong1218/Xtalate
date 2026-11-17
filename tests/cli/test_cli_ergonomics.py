"""CLI ergonomics (QoL track Q): target inference, actionable refusals, the scenarios command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = str(GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")  # 2-frame plain XYZ, no cell
CO_IN_CELL = str(GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")  # 1 frame, with a cell


def _json_out(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(capsys.readouterr().out))


# --- -o extension infers --to ---------------------------------------------------------------


def test_unique_extension_infers_target(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.cif"  # ".cif" is claimed by exactly one writable format (cif)
    rc = main(["convert", CO_IN_CELL, "-o", str(out)])
    assert rc == EXIT_OK, capsys.readouterr().err
    assert out.read_text().lstrip().startswith("data_")  # a CIF data block, not extXYZ/XYZ


def test_ambiguous_extension_names_the_candidates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["convert", CO_IN_CELL, "-o", str(tmp_path / "out.xyz")])
    err = capsys.readouterr().err
    assert rc == EXIT_USAGE
    assert ".xyz matches" in err
    assert "pass --to xyz or --to extxyz" in err
    assert not (tmp_path / "out.xyz").exists()


def test_unknown_extension_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["convert", CO_IN_CELL, "-o", str(tmp_path / "out.nope")])
    assert rc == EXIT_USAGE
    assert "--to" in capsys.readouterr().err


def test_explicit_to_always_wins_over_extension(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.xyz"
    rc = main(["convert", CO_IN_CELL, "-o", str(out), "--to", "extxyz"])
    assert rc == EXIT_OK, capsys.readouterr().err
    assert out.read_text().splitlines()[1].startswith("Lattice=")  # extXYZ comment line


def test_no_output_and_no_to_still_requires_to(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["convert", CO_IN_CELL]) == EXIT_USAGE
    assert "--to" in capsys.readouterr().err


# --- refusal guidance -------------------------------------------------------------------------


def test_refusal_prints_description_choices_and_copyable_recover_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # water_traj has two frames and no cell; POSCAR needs one frame and a lattice.
    rc = main(["convert", WATER, "--to", "poscar", "-o", str(tmp_path / "w.poscar")])
    out = capsys.readouterr().out
    assert rc == EXIT_REFUSED
    assert "To resolve" in out
    assert "--recover frame_selection=first" in out
    assert "--recover frame_selection=index,frame_index=0" in out
    assert "--recover missing_lattice=bounding_box,padding_ang=5.0" in out
    # The description of a choice is printed, not just its code.
    assert "bounding box" in out.lower()


def test_guidance_is_not_in_json_stdout(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rc = main(["convert", WATER, "--to", "poscar", "-o", str(tmp_path / "w.poscar"), "--json"])
    payload = _json_out(capsys)  # stdout must remain pure JSON
    assert rc == EXIT_REFUSED
    assert payload["conversion_report"]["status"] == "refused"


def test_every_copyable_recover_example_parses_and_names_an_offered_choice() -> None:
    """The flags the guidance prints must be accepted by the real ``--recover`` grammar and name a
    choice the scenario really offers, with only parameter names the resolver reads."""
    from xtalate.cli.main import _parse_recover
    from xtalate.cli.render import _RECOVER_EXAMPLES, _offered_choices

    known_params = {"padding_ang", "frame_index", "row", "temperature_K", "seed"}
    for (scenario, choice), spec in _RECOVER_EXAMPLES.items():
        parsed = _parse_recover([spec])
        assert parsed[scenario]["choice"] == choice, spec
        assert choice in _offered_choices(scenario), spec
        assert set(parsed[scenario]["parameters"]) <= known_params, spec


# --- xtalate scenarios ------------------------------------------------------------------------


def test_scenarios_lists_every_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios"]) == EXIT_OK
    out = capsys.readouterr().out
    for name in ("missing_lattice", "frame_selection", "missing_velocities"):
        assert name in out


def test_scenarios_one_scenario_shows_choices(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "missing_lattice"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "bounding_box" in out and "manual_input" in out


def test_scenarios_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "--json"]) == EXIT_OK
    payload = _json_out(capsys)
    assert payload["missing_lattice"]["hazard_class"] == "fabricative"
    assert "bounding_box" in payload["missing_lattice"]["choices"]
    assert payload["missing_lattice"]["choices"]["bounding_box"]  # non-empty description


def test_scenarios_unknown_name_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "nope"]) == EXIT_USAGE
    assert "known scenarios" in capsys.readouterr().err


# --- fix round 1 ------------------------------------------------------------------------------


def test_every_emitted_recover_flag_is_accepted_by_the_real_parser() -> None:
    """Every flag ``_recover_flag`` emits, for every offered pair, parses and names that choice."""
    from xtalate.cli.main import _parse_recover
    from xtalate.cli.render import _offered_choices, _recover_flag
    from xtalate.recovery.scenarios import SCENARIO_HAZARD

    emitted = 0
    for scenario in SCENARIO_HAZARD:
        for choice in _offered_choices(scenario):
            flag = _recover_flag(scenario, choice)
            if flag is None:
                continue
            assert flag.startswith("--recover ")
            parsed = _parse_recover([flag.removeprefix("--recover ")])
            assert parsed[scenario]["choice"] == choice, flag
            emitted += 1
    assert emitted > 10


def test_non_periodic_is_not_advertised_as_a_copyable_flag() -> None:
    from xtalate.cli.render import _recover_flag
    from xtalate.recovery.scenarios import describe_choice

    assert _recover_flag("missing_lattice", "non_periodic") is None
    assert "not yet available" in describe_choice("missing_lattice", "non_periodic").lower()


def test_api_only_choices_say_so_in_the_catalog(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "missing_lattice"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "HTTP API" in out
