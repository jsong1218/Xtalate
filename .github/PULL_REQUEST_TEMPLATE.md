<!-- Thanks for contributing to Xtalate. Keep PRs small and single-purpose. -->

## What & why

<!-- What does this change do, and why? For any nontrivial design decision, name at least
     one reasonable rejected alternative — the standard the whole doc set holds itself to. -->

## Rejected alternative (for design changes)

<!-- e.g. "Considered threading choices into build_preflight; rejected because it breaks the
     draft's purity (D46)." Delete this section only for pure docs/typo PRs. -->

## Checklist

- [ ] **Docs updated or confirmed unaffected.** The docs are authoritative; a behavior
      change and its doc change are one PR.
- [ ] **Golden cases added** for new behavior, each with a licensed `manifest.yaml`,
      and `tests/golden/ATTRIBUTIONS.md` regenerated (`python
      tests/golden/_governance.py`) if any manifest changed.
- [ ] **No parser defaulting introduced** — the absence convention holds and the
      default-laundering suite passes (P3).
- [ ] **Completeness invariant green** — the runtime assertion and the property suite
      (`tests/property/`) both pass; no field is lost, dropped, or fabricated silently (P1/P4).
- [ ] **Capability declarations updated** and the capability-table sync test is green.
- [ ] **Rejected alternative named** in the description for design changes.
- [ ] **Attribution file regenerates cleanly** — the governance suite
      (`tests/golden/test_corpus_governance.py`) is green.
- [ ] **Contributed files carry license grants** — for any file added under
      `origin.kind: contributed`, I have the right to contribute it and grant it under the
      recorded license (Apache-2.0 or a compatible data license).
- [ ] **Full local gate passed:** `ruff check .`, `ruff format --check .`, `mypy`,
      `lint-imports`, `pytest`.
