"""The shared VASP core's stress mapping (v1.2 M42-S3; DECISIONS.md D161).

The core is the mapping layer vasprun.xml and (M43) OUTCAR share, so its stress transform is
pinned here on its own: the exact kBar → eV/Å³ factor, the compression→tension sign flip, and
the VASP Voigt-6 ordering — the last **deliberately not** ASE's, because coupling the two
orderings would silently transpose the off-diagonal stress components (the hazard D161 names).
"""

from __future__ import annotations

import numpy as np

from xtalate.parsers._vasp import (
    K_BAR_PER_EV_A3,
    stress_from_vasp_kbar,
    stress_voigt6_vasp_to_full,
)


def test_exact_kbar_factor_is_1602_1766208() -> None:
    # The constant is the exact 1 eV/Å³ ⇔ kBar conversion, not an approximation: a wrong
    # factor would be a silent scale error at MLIP scale (D161). 1602.1766208 kBar must map
    # to exactly 1.0 eV/Å³ before the sign flip.
    assert K_BAR_PER_EV_A3 == 1602.1766208
    assert stress_from_vasp_kbar([[K_BAR_PER_EV_A3]]).tolist() == [[-1.0]]


def test_sign_flip_compressive_to_tension_positive() -> None:
    # A known *compressive* state — positive diagonal in kBar (VASP writes pressure) — reads
    # *negative* tension in canonical eV/Å³ (Part 2 §3.7.1): the flip is pinned, not assumed.
    tensor = stress_from_vasp_kbar(
        [
            [K_BAR_PER_EV_A3, 0.0, 0.0],
            [0.0, K_BAR_PER_EV_A3, 0.0],
            [0.0, 0.0, K_BAR_PER_EV_A3],
        ]
    )
    assert tensor.tolist() == [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]


def test_exact_factor_on_off_diagonal() -> None:
    tensor = stress_from_vasp_kbar(
        [
            [K_BAR_PER_EV_A3, K_BAR_PER_EV_A3 / 2, 0.0],
            [K_BAR_PER_EV_A3 / 2, 2 * K_BAR_PER_EV_A3, 0.0],
            [0.0, 0.0, K_BAR_PER_EV_A3 / 10],
        ]
    )
    assert tensor.tolist() == [
        [-1.0, -0.5, 0.0],
        [-0.5, -2.0, 0.0],
        [0.0, 0.0, -0.1],
    ]


def test_voigt6_vasp_ordering_is_xx_yy_zz_xy_yz_zx() -> None:
    # VASP's OUTCAR stress line is the 6-component Voigt form in VASP's own order
    # [XX, YY, ZZ, XY, YZ, ZX]. The off-diagonal placement is what M43's OUTCAR reader depends
    # on — pin each component to a distinct value so a transposed ordering fails loudly.
    full = stress_voigt6_vasp_to_full([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert full.tolist() == [
        [1.0, 4.0, 6.0],
        [4.0, 2.0, 5.0],
        [6.0, 5.0, 3.0],
    ]


def test_voigt6_vasp_ordering_is_not_ase_ordering() -> None:
    # The hazard D161 names, in code: ASE's voigt_6_to_full_3x3_stress uses
    # [xx, yy, zz, yz, xz, xy] — the YZ/ZX-XY positions swap. Feed the same 6 values through
    # both and show the tensors differ (i.e. the VASP helper is not a silent alias of ASE's).
    from ase.stress import voigt_6_to_full_3x3_stress

    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    vasp = stress_voigt6_vasp_to_full(values)
    ase_tensor = voigt_6_to_full_3x3_stress(np.asarray(values))
    assert vasp.tolist() != ase_tensor.tolist()
    # Spot-check the exact difference: ASE puts v[3]=4 at [1][2] (yz); VASP's [1][2] is v[4].
    assert ase_tensor.tolist()[1][2] == 4.0
    assert vasp.tolist()[1][2] == 5.0


def test_voigt6_ordering_only_no_unit_or_sign() -> None:
    # The helper is ordering-only by design (D161): the caller applies the kBar → eV/Å³ unit
    # and the compression→tension sign flip via stress_from_vasp_kbar. An isotropic 1 kBar
    # compressive line must therefore come back as +1 on the diagonal from the helper, then
    # -1/1602.1766208 from the transform.
    full = stress_voigt6_vasp_to_full([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    assert full.tolist() == np.eye(3).tolist()
    got = stress_from_vasp_kbar(full)
    assert np.allclose(got, np.eye(3) * (-1.0 / K_BAR_PER_EV_A3))
