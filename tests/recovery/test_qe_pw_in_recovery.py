"""``missing_species`` recovery on the QE pw.x input reader (v1.4 M50-S3; DECISIONS.md D191).

The QE counterpart of the LAMMPS species recovery: an ``ATOMIC_SPECIES`` label whose
leading 1–2 characters form no element (``Zz`` here) is a genuine unknown — the parser
refuses ``QEIN_UNRESOLVED_SPECIES_LABEL`` with the shared ``supply_species`` hint, and the
read completes only through the **existing** ``missing_species`` scenario (``species_map``
or ``upload_reference``). No QE-specific recovery is invented: the hazard is identical to
the LAMMPS parsers', so one scenario is reused (D191, rejected alternative (a)). Without a
preset the file is refused; with one, the supplied symbols are applied, the recovery is
recorded as an ``Assumption`` and a ``QEIN_SPECIES_SUPPLIED`` warning, and the declared
masses/pseudopotentials ride the completed read (P1, P3).
"""

from __future__ import annotations

import pytest

from xtalate.conversion.parse_recovery import parse_with_recovery
from xtalate.registry import default_registry
from xtalate.sdk import ParseError

_REGISTRY = default_registry()

#: A pw.x input whose second species label (``Zz``) resolves to no element.
_UNRESOLVABLE = """\
&SYSTEM
   ibrav = 0, nat = 2, ntyp = 2,
/
ATOMIC_SPECIES
   Fe1 55.845 fe.pbe.UPF
   Zz 15.999 zz.pbe.UPF
ATOMIC_POSITIONS {angstrom}
   Fe1 1.0 2.0 3.0
   Zz 3.0 2.0 1.0
CELL_PARAMETERS {angstrom}
   3.0 1.0 0.0
   0.0 4.0 1.0
   1.0 0.0 5.0
"""

_SPECIES_MAP: dict[str, dict[str, object]] = {
    "missing_species": {
        "choice": "species_map",
        "parameters": {"species": {"Fe1": "Fe", "Zz": "O"}},
    }
}


def test_without_a_preset_the_unresolvable_label_is_refused() -> None:
    """Refusal is the default (Part 4 §4): silently mapping the unknown label to an element
    would be the engine guessing, exactly what P4 forbids."""
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(_REGISTRY, _UNRESOLVABLE.encode(), filename="pw.in")
    issue = exc.value.issues[0]
    assert issue.code == "QEIN_UNRESOLVED_SPECIES_LABEL"
    assert issue.recovery_hint == "supply_species"


def test_species_map_completes_the_read() -> None:
    recovery = parse_with_recovery(
        _REGISTRY, _UNRESOLVABLE.encode(), filename="pw.in", recovery_choices=_SPECIES_MAP
    )
    obj = recovery.canonical
    assert obj.frames[0].atoms.symbols == ["Fe", "O"]
    # The declared masses/pseudopotentials ride the completed read (nothing dropped).
    masses = obj.frames[0].atoms.masses
    assert masses is not None
    assert masses.tolist() == [55.845, 15.999]
    assert obj.user_metadata.custom_global["qe:pseudopotentials"] == {
        "Fe1": "fe.pbe.UPF",
        "Zz": "zz.pbe.UPF",
    }


def test_the_supplied_species_are_recorded_as_an_assumption() -> None:
    recovery = parse_with_recovery(
        _REGISTRY, _UNRESOLVABLE.encode(), filename="pw.in", recovery_choices=_SPECIES_MAP
    )
    assert len(recovery.assumptions) == 1
    assumption = recovery.assumptions[0]
    assert assumption.scenario == "missing_species"
    assert assumption.choice == "species_map"
    assert any(
        issue.code == "QEIN_SPECIES_SUPPLIED" and issue.severity == "warning"
        for issue in recovery.issues
    )


def test_an_unresolvable_map_value_is_an_honest_blocker() -> None:
    """A species_map whose value is itself not an element is refused — the recovery can't
    fabricate a symbol, and the engine surfaces the re-raised need rather than guessing."""
    bad_map: dict[str, dict[str, object]] = {
        "missing_species": {
            "choice": "species_map",
            "parameters": {"species": {"Fe1": "Fe", "Zz": "NotAnElement"}},
        }
    }
    with pytest.raises(ParseError) as exc:
        parse_with_recovery(
            _REGISTRY, _UNRESOLVABLE.encode(), filename="pw.in", recovery_choices=bad_map
        )
    assert exc.value.issues[0].code == "QEIN_UNRESOLVED_SPECIES_LABEL"
