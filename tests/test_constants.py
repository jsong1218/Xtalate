"""Single source of truth for physical constants (A1). Derived constants are cross-checked
against their definitions; an AST scan keeps long float literals out of the rest of src/."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from xtalate import _constants as c

SRC = Path(__file__).parent.parent / "src" / "xtalate"


def test_si_exact_definitions() -> None:
    assert c.N_A == 6.02214076e23
    assert c.E_CHARGE == 1.602176634e-19
    assert c.AMU_KG == 1.66053906660e-27


def test_derived_energy_factors() -> None:
    assert c.RYDBERG_EV == pytest.approx(c.HARTREE_EV / 2, rel=0, abs=0)
    assert c.RYDBERG_EV == 13.605693122994
    assert c.KCAL_PER_MOL_EV == pytest.approx(4184.0 / (c.N_A * c.E_CHARGE), rel=1e-15)
    assert c.KJ_PER_MOL_EV == pytest.approx(1000.0 / (c.N_A * c.E_CHARGE), rel=1e-15)
    assert c.J_TO_EV == pytest.approx(1.0 / c.E_CHARGE, rel=1e-15)
    assert c.KG_TO_AMU == pytest.approx(1.0 / c.AMU_KG, rel=1e-15)


def test_kj_per_mol_is_the_correct_value() -> None:
    # The old h5md literal 0.010364269574 was wrong from the 9th digit.
    assert c.KJ_PER_MOL_EV == pytest.approx(0.010364269656262174, rel=1e-14)


def test_pinned_values_are_close_to_codata_2018() -> None:
    # Kept on purpose (goldens/fixtures are pinned to them); both editions are exported.
    assert c.BOHR_TO_ANGSTROM_QE == 0.52917720859
    assert c.K_BAR_PER_EV_A3 == 1602.1766208
    assert c.K_BAR_PER_EV_A3_CODATA2018 == pytest.approx(1602.176634, rel=1e-15)
    assert abs(c.BOHR_TO_ANGSTROM_QE / c.BOHR_TO_ANGSTROM_CODATA2018 - 1) < 1e-8
    assert abs(c.K_BAR_PER_EV_A3 / c.K_BAR_PER_EV_A3_CODATA2018 - 1) < 1e-8


def test_each_constant_names_its_codata_edition() -> None:
    # Provenance guard: the mixed-edition decision must stay visible in the source.
    text = (SRC / "_constants.py").read_text(encoding="utf-8")
    for needle in ("SI 2019", "CODATA 2018", "CODATA 2006", "CODATA 2014", "pinned"):
        assert needle in text, needle


def test_downstream_modules_use_the_shared_values() -> None:
    from xtalate.parsers._qe import BOHR_TO_ANGSTROM
    from xtalate.parsers._qe.labels import (
        FORCES_FACTOR,
        K_BAR_PER_RY_BOHR3,
        RY_TO_EV,
        STRESS_FACTOR,
    )
    from xtalate.parsers._vasp.labels import K_BAR_PER_EV_A3

    assert BOHR_TO_ANGSTROM == c.BOHR_TO_ANGSTROM_QE
    assert RY_TO_EV == c.RYDBERG_EV
    assert K_BAR_PER_EV_A3 == c.K_BAR_PER_EV_A3
    assert FORCES_FACTOR == pytest.approx(25.71103385054424, rel=1e-14)
    assert STRESS_FACTOR == pytest.approx(91.8157694288102, rel=1e-14)
    assert K_BAR_PER_RY_BOHR3 == pytest.approx(147105.07919960306, rel=1e-14)
    assert math.isfinite(K_BAR_PER_RY_BOHR3)


def _long_float_literals(path: Path) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    text = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            seg = ast.get_source_segment(text, node) or ""
            digits = "".join(ch for ch in seg.split("e")[0].split("E")[0] if ch.isdigit()).lstrip(
                "0"
            )
            if len(digits) >= 8:
                out.append((node.lineno, node.value))
    return out


#: Long float literals that are NOT physical/unit constants (tolerances, published test
#: values, format-defined numbers). The scan of the tree found long float literals ONLY in the
#: constant sites Task 1 replaced, so the expected value is exactly `{}`.
ALLOWED_LONG_FLOATS: dict[str, set[float]] = {}


def test_no_long_float_literal_outside_constants_module() -> None:
    offenders = {}
    for path in SRC.rglob("*.py"):
        if path.name == "_constants.py":
            continue
        rel = str(path.relative_to(SRC))
        hits = [
            h for h in _long_float_literals(path) if h[1] not in ALLOWED_LONG_FLOATS.get(rel, set())
        ]
        if hits:
            offenders[rel] = hits
    assert offenders == {}, f"physical constants must live in xtalate/_constants.py: {offenders}"


def test_known_constant_digit_strings_do_not_appear_in_string_literals() -> None:
    needles = ("1602.1766208", "0.52917720859", "13.605693122994", "27.211386245988")
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "_constants.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if any(n in node.value for n in needles):
                    offenders.append((str(path.relative_to(SRC)), node.lineno))
    assert offenders == [], offenders
