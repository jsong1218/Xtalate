"""CLI tests for the ``--repair`` flag (v1.7 M66-S1, D255).

Drives ``main(argv)`` end to end and pins the ordered-list grammar: repeated
``--repair OPERATION[,param=value…]`` builds a ``list[RepairRequest]`` applied in argument
order (order is scientific meaning — wrap-then-center ≠ center-then-wrap, and the report
records which happened), a bad request is a clean usage error (exit 1), a blocked repair (a
cell-less wrap) refuses through the ordinary refusal path (exit 2) fabricating nothing — or,
when the caller pre-supplied the matching ``--recover missing_lattice=…`` preset (v1.7.0,
D260), resolves in place: the choice is applied to the object before the repair is retried,
so the conversion completes. A no-``--repair`` run is byte-identical to a pre-v1.7 one (the
opt-in invariant).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from xtalate.cli.main import EXIT_OK, EXIT_REFUSED, EXIT_USAGE, main

GOLDEN = Path(__file__).parent.parent / "golden"
WATER = str(GOLDEN / "xyz" / "water-traj" / "water_traj.xyz")
CO_IN_CELL = str(GOLDEN / "extxyz" / "co-in-cell" / "sample.extxyz")
NACL_CIF = str(GOLDEN / "cif" / "nacl-fm3m" / "nacl_fm3m.cif")

# An unwrapped variant of CO_IN_CELL: the C atom pushed one lattice vector (6 Å) outside the
# box, so a wrap genuinely folds atoms. (CO_IN_CELL itself is already in-cell, so wrapping it
# is a no-op that v1.7.0 correctly leaves unwarned — the R5 fixtures write this to disk.)
UNWRAPPED_EXTXYZ = (
    "2\n"
    'Lattice="6.0 0.0 0.0 0.0 6.0 0.0 0.0 0.0 6.0" '
    "Properties=species:S:1:pos:R:3:masses:R:1:forces:R:3:charge:R:1 "
    'pbc="T T T" energy=-14.25 config_type=diatomic\n'
    "C 7.0 1.0 1.0 12.011 0.5 0.0 0.0 0.3\n"
    "O 2.125 1.0 1.0 15.999 -0.5 0.0 0.0 -0.3\n"
)


def _json_payload(capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(capsys.readouterr().out))


def _repair_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The report's repairs section, recovered from the serialized ``assumptions`` view."""
    return [a for a in payload["conversion_report"]["assumptions"] if a["scenario"] == "repair"]


def _repair_warnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in payload["conversion_report"]["warnings"] if w["source"] == "repair"]


# --- the flagship: a requested wrap converts, recorded + warned ------------------------------


def test_repair_wrap_converts_and_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The unwrapped variant: a wrap that genuinely folds atoms carries the R5 warning (a
    # no-op wrap of an already-in-cell structure correctly carries none since v1.7.0).
    source = tmp_path / "unwrapped.extxyz"
    source.write_text(UNWRAPPED_EXTXYZ)
    out = tmp_path / "wrapped.extxyz"
    code = main(
        ["convert", str(source), "--to", "extxyz", "-o", str(out), "--repair", "wrap_into_cell"]
    )
    assert code == EXIT_OK
    assert out.exists() and out.read_bytes()
    capsys.readouterr()  # discard the human rendering; the --json run below is the assertion.

    # Under --json the report carries the wrap Assumption + the R5 warning.
    code = main(["convert", str(source), "--to", "extxyz", "--repair", "wrap_into_cell", "--json"])
    assert code == EXIT_OK
    payload = _json_payload(capsys)
    assert payload["conversion_report"]["status"] == "completed"
    assert payload["validation_report"]["status"] == "passed"

    (row,) = _repair_rows(payload)
    assert row["choice"] == "wrap_into_cell"
    assert row["origin"] == "preset"
    assert "Wrapped all atom positions into the simulation cell" in row["description"]
    (warning,) = _repair_warnings(payload)
    assert warning["code"] == "WRAP_DISCARDS_UNWRAPPED_PATHS"


# --- order is scientific meaning -------------------------------------------------------------


def test_repair_order_matters_and_is_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(flags: list[str]) -> tuple[bytes, list[str]]:
        out = tmp_path / f"{flags[1]}-{flags[3]}.extxyz"
        code = main(["convert", CO_IN_CELL, "--to", "extxyz", "-o", str(out), *flags, "--json"])
        assert code == EXIT_OK
        return out.read_bytes(), [row["choice"] for row in _repair_rows(_json_payload(capsys))]

    center_first = run(
        ["--repair", "center,reference=centroid,target=origin", "--repair", "wrap_into_cell"]
    )
    wrap_first = run(
        ["--repair", "wrap_into_cell", "--repair", "center,reference=centroid,target=origin"]
    )

    # Different order -> different structure (wrap folds the centered positions back into the
    # box), and each report records its own stack in application order.
    assert center_first[0] != wrap_first[0]
    assert center_first[1] == ["center", "wrap_into_cell"]
    assert wrap_first[1] == ["wrap_into_cell", "center"]


# --- repair-only same-format run validates green ---------------------------------------------


def test_repair_only_same_format_run_validates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "reordered.cif"
    code = main(["convert", NACL_CIF, "--to", "cif", "-o", str(out), "--repair", "species_reorder"])
    assert code == EXIT_OK
    assert out.exists() and out.read_bytes()
    capsys.readouterr()  # discard the human rendering; the --json run below is the assertion.

    code = main(["convert", NACL_CIF, "--to", "cif", "--repair", "species_reorder", "--json"])
    assert code == EXIT_OK
    payload = _json_payload(capsys)
    assert payload["conversion_report"]["status"] == "completed"
    # CIF is a lossy target, so validation may pass-with-warnings — "green" either way.
    assert payload["validation_report"]["status"] in ("passed", "passed_with_warnings")
    (row,) = _repair_rows(payload)
    assert row["choice"] == "species_reorder"
    assert "permutation" in row["parameters"]  # the recorded map makes the repair reproducible


# --- bad --repair is a clean usage error (exit 1) --------------------------------------------


@pytest.mark.parametrize(
    "flag",
    [
        "teleport",  # unknown operation
        "deduplicate",  # missing required distance_threshold
        "center,reference=centroid",  # missing required target
        "center,reference=barycenter,target=origin",  # incoherent parameter value
        "wrap_into_cell,stray",  # non-key=value fragment
        ",param=1",  # empty operation name
    ],
)
def test_repair_usage_errors_are_clean_exit_1(
    flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["convert", CO_IN_CELL, "--to", "extxyz", "--repair", flag])
    assert code == EXIT_USAGE
    captured = capsys.readouterr()
    assert "error: invalid --repair:" in captured.err
    assert "Traceback" not in captured.err


# --- a cell-less wrap refuses (exit 2) and fabricates nothing --------------------------------


def test_repair_cell_less_wrap_refuses_via_missing_lattice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "wrapped.xyz"
    code = main(
        ["convert", WATER, "--to", "xyz", "-o", str(out), "--repair", "wrap_into_cell", "--json"]
    )
    assert code == EXIT_REFUSED
    assert not out.exists()  # a refused conversion produces no output file.

    payload = _json_payload(capsys)
    report = payload["conversion_report"]
    assert report["status"] == "refused"
    # The refusal routes through the existing missing_lattice recovery — nothing is fabricated
    # to un-block the wrap, and no repair was applied.
    assert "missing_lattice" in json.dumps(report)
    assert report["supplied"] == []
    assert _repair_rows(payload) == []


def test_repair_cell_less_wrap_resolves_in_place_with_a_preset(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # v1.7.0 (D260): the blocked repair resolves through the pre-supplied recovery — the
    # --recover preset is applied to the object before the repair is retried, so the
    # conversion completes instead of refusing (the refusal test above pins the no-preset
    # behaviour).
    out = tmp_path / "wrapped.xyz"
    code = main(
        [
            "convert",
            WATER,
            "--to",
            "xyz",
            "-o",
            str(out),
            "--repair",
            "wrap_into_cell",
            "--recover",
            "missing_lattice=bounding_box,padding_ang=5.0",
            "--json",
        ]
    )
    assert code == EXIT_OK
    assert out.exists() and out.read_bytes()
    payload = _json_payload(capsys)
    report = payload["conversion_report"]
    assert report["status"] == "completed"
    # Application order: the recovery that un-blocked the wrap precedes the repair row.
    assert [(a["scenario"], a["choice"]) for a in report["assumptions"]] == [
        ("missing_lattice", "bounding_box"),
        ("repair", "wrap_into_cell"),
    ]
    assert [r["choice"] for r in _repair_rows(payload)] == ["wrap_into_cell"]
    # The fabricated cell is accounted as supplied — never silently invented.
    assert any(s["path"] == "cell.lattice_vectors" for s in report["supplied"])


# --- the opt-in invariant: no --repair is byte-identical -------------------------------------


def test_no_repair_run_is_byte_identical(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "plain.extxyz"

    def run() -> tuple[bytes, dict[str, Any]]:
        code = main(["convert", CO_IN_CELL, "--to", "extxyz", "-o", str(out), "--json"])
        assert code == EXIT_OK
        return out.read_bytes(), _json_payload(capsys)

    first_bytes, first_payload = run()
    second_bytes, second_payload = run()

    # Deterministic: the same invocation produces the same artifact and the same report
    # modulo the legitimately-varying record identifiers and timestamps (UUIDs/clock per
    # report; they are the audit identity, not scientific content).
    assert first_bytes == second_bytes

    def stable(payload: dict[str, Any]) -> dict[str, Any]:
        def scrub(node: object) -> Any:
            if isinstance(node, dict):
                return {
                    k: scrub(v)
                    for k, v in node.items()
                    if k not in {"report_id", "created_at", "conversion_report_id"}
                }
            if isinstance(node, list):
                return [scrub(item) for item in node]
            return node

        return cast(dict[str, Any], scrub(payload))

    assert stable(first_payload) == stable(second_payload)
    # The opt-in invariant: an absent repairs list runs exactly the pre-v1.7 pipeline — the
    # report serializes with no repairs / repair_warnings keys at all (derived views, D250).
    assert "repairs" not in first_payload["conversion_report"]
    assert "repair_warnings" not in first_payload["conversion_report"]


# --- --repair is single-file only in v1.7 ----------------------------------------------------


def test_repair_is_refused_in_batch_mode(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["convert", "--batch", "manifest.yaml", "--repair", "wrap_into_cell"])
    assert code == EXIT_USAGE
    assert "--repair cannot be used with --batch" in capsys.readouterr().err
