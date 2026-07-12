"""Format Sniffer (Part 3 §6.1) — winner selection, UNKNOWN_FORMAT with candidate
list, ambiguity margin, the POSCAR⇄CONTCAR filename rule, and the expressiveness
tie-break — all exercised through dummy parsers, proving the sniffer stays generic."""

from __future__ import annotations

from tests._dummy_plugins import DummyParser
from xtalate.capabilities import Registry
from xtalate.discovery import Sniffer


def _registry(*parsers: DummyParser) -> Registry:
    reg = Registry()
    for p in parsers:
        reg.register_parser(p)
    return reg


def test_clear_winner_is_selected() -> None:
    # §6.3: plain XYZ scores high, extXYZ low (no Lattice=/Properties= keys).
    reg = _registry(
        DummyParser("xyz", score=0.9),
        DummyParser("extxyz", score=0.2),
    )
    result = Sniffer(reg).sniff(b"3\nframe 0\nO 0 0 0\n")
    assert result.format_id == "xyz"
    assert result.confidence == 0.9
    assert result.ambiguous is False
    assert [c.format_id for c in result.candidates] == ["xyz", "extxyz"]


def test_below_threshold_is_unknown_with_candidates() -> None:
    reg = _registry(
        DummyParser("xyz", score=0.3),
        DummyParser("extxyz", score=0.1),
    )
    result = Sniffer(reg).sniff(b"garbage")
    assert result.format_id is None  # UNKNOWN_FORMAT
    assert result.confidence == 0.3
    # candidate list is still reported so the caller can see/override
    assert [c.format_id for c in result.candidates] == ["xyz", "extxyz"]


def test_no_registered_parsers_is_unknown() -> None:
    result = Sniffer(Registry()).sniff(b"anything")
    assert result.format_id is None
    assert result.candidates == []


def test_close_scores_flagged_ambiguous() -> None:
    reg = _registry(
        DummyParser("a", score=0.6),
        DummyParser("b", score=0.55),  # margin 0.05 < 0.2
    )
    result = Sniffer(reg).sniff(b"x")
    assert result.format_id == "a"  # still picks the top score
    assert result.ambiguous is True


def test_wide_margin_not_ambiguous() -> None:
    reg = _registry(
        DummyParser("a", score=0.9),
        DummyParser("b", score=0.4),  # margin 0.5 >= 0.2
    )
    assert Sniffer(reg).sniff(b"x").ambiguous is False


def test_thresholds_are_configurable() -> None:
    reg = _registry(DummyParser("a", score=0.45))
    assert Sniffer(reg).sniff(b"x").format_id is None  # 0.45 < default 0.5
    assert Sniffer(reg, accept_threshold=0.4).sniff(b"x").format_id == "a"


def test_expressiveness_tiebreak_via_signature() -> None:
    # extXYZ is a superset of XYZ; when its Lattice= signature is present it outscores XYZ.
    reg = _registry(
        DummyParser("xyz", score=0.6),
        DummyParser("extxyz", signature=b'Lattice="'),
    )
    with_lattice = Sniffer(reg).sniff(b'Lattice="5 0 0 0 5 0 0 0 5"\n')
    assert with_lattice.format_id == "extxyz"  # 0.95 beats 0.6


# --- POSCAR ⇄ CONTCAR (§6.1): resolution is filename-driven, via parser scores ---------


def _poscar_contcar_registry() -> Registry:
    # Both structurally similar; contcar scores marginally lower on a nameless generic file
    # (it is the more specific claim), so POSCAR wins a nameless tie. Exact conventional
    # names select decisively (1.0).
    return _registry(
        DummyParser("poscar", score=0.6, conventional_name="POSCAR"),
        DummyParser("contcar", score=0.55, conventional_name="CONTCAR"),
    )


def test_exact_poscar_name_selects_poscar() -> None:
    result = Sniffer(_poscar_contcar_registry()).sniff(b"...", filename="POSCAR")
    assert result.format_id == "poscar"
    assert result.confidence == 1.0
    assert result.ambiguous is False


def test_exact_contcar_name_selects_contcar() -> None:
    result = Sniffer(_poscar_contcar_registry()).sniff(b"...", filename="CONTCAR")
    assert result.format_id == "contcar"
    assert result.confidence == 1.0


def test_nameless_poscar_contcar_prefers_poscar_but_flags_ambiguity() -> None:
    # §6.1 step (3): parsed as poscar (more general), tie recorded so the user can override.
    result = Sniffer(_poscar_contcar_registry()).sniff(b"generic vasp-shaped content")
    assert result.format_id == "poscar"
    assert result.ambiguous is True
    assert {c.format_id for c in result.candidates} == {"poscar", "contcar"}
