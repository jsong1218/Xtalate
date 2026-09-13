# xtalate-analysis-composition

The reference **analysis** plugin for Xtalate (M69): element counts, a reduced Hill formula, and
mass density. The science is deliberately trivial — the plugin's job is to model the pattern a
third-party analysis plugin follows, and to do it with exemplary honesty.

## What it writes

All results land under the plugin's own `composition:` namespace in
`user_metadata.custom_global`:

| Key | Meaning |
|---|---|
| `composition:formula` | Reduced empirical formula, Hill notation (e.g. `H2O`, `C2H6O`). |
| `composition:element_counts` | Per-element atom counts for frame 0. |
| `composition:atom_count` | Total atoms in frame 0. |
| `composition:mass_density_g_per_cm3` | Mass density of frame 0 — or `null` when not computable. |
| `composition:density_note` | How the density was computed, or the stated reason it was not. |

## Honest absence (P3/P4)

Density needs a cell **and** masses. A cell-less object gets `null` and
`"no simulation cell declared in the source"`; an object without masses gets `null` and a note
that **this plugin never fills masses** — filling absent data is recovery's job, and recovery is
explicit. The plugin never fabricates data the source did not contain.

## Install

```bash
pip install ./plugins/xtalate-analysis-composition
```

Once installed, `xtalate`'s `default_registry()` discovers it through the `xtalate.analysis`
entry-point group, exactly like any third-party analysis plugin.
