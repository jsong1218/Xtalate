from xtalate.exporters.extxyz import ExtxyzExporter
from xtalate.validation.engine import _representational_bound


def test_extxyz_positions_get_a_half_ulp_bound() -> None:
    prec = ExtxyzExporter().capabilities().numeric_precision
    assert _representational_bound(prec, "atoms.positions") == 0.5 * 10**-8
    assert _representational_bound(prec, "electronic.total_energy") == 0.0
