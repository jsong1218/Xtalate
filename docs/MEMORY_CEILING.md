# Xtalate — Memory Ceiling (streaming core)

> **Status.** Introduced with M12 (v0.3, "Trajectories at Scale"), the frame-chunked processing
> core, and extended with M13 (XDATCAR — the streaming-first parser and the `frame_selection`
> streaming path D56 deferred here). This note states the memory model the streaming path guarantees
> and records its measured validation. The numbers here are seeded from the M12/M13 proof fixtures;
> M15 finalizes them against the full synthetic performance corpus (`docs/IMPLEMENTATION_PLAN_v0.3.md`
> M15 deliverable 4).

## The model

For a conversion taken through the **streaming path** (`ConversionEngine.convert_stream`, or the raw
`sdk.streaming.parse_as_stream` → `export_stream`), peak resident memory is

```
peak_memory  ∝  chunk_size × atoms_per_frame        (NOT  ∝  frame_count)
```

A trajectory is processed one frame at a time: the parser yields a `StreamFrame`, the engine
filters it through the capability write plan and hands it straight to the streaming exporter, and
the frame is released before the next is read. Nothing that scales with the number of frames is
held resident — not the source text (read block by block off the byte stream), not the `Frame`
pydantic objects, not the output bytes (written straight through to the target stream). The eager
`StreamHeader` holds only object-level metadata whose size is independent of frame count.

`chunk_size` is 1 frame in the v0.3 implementation (frame-at-a-time). The interface leaves room for
a larger chunk later — the bound is stated in terms of `chunk_size` so raising it stays a tuning
change behind the same interface (P6), never a change to the guarantee's shape.

### What is *not* on the streaming path

- **`frame_selection` into a single-structure target** (e.g. XDATCAR → POSCAR) *is* on the streaming
  path as of M13 (`ConversionEngine.convert_stream_select`; DECISIONS.md D56): a single pass
  accumulates full field presence and counts frames while capturing *only* the one retained frame
  (`first`/`last`/`index` by bounded lookback — at most the frame-0, running-last, and `index=k`
  candidates resident), then exports and validates that single frame. Peak is `∝ atoms_per_frame`,
  not `∝ frame_count`, and the Conversion Report and output bytes are byte-identical to the
  materialized `convert` on the same file (standing rule 3). `bounding_box` on the selected frame is
  the *general* mechanism for a target that also lacks a lattice; it never fires for XDATCAR (which
  always carries one), and a file whose retained frame would still need a fabricative recovery is
  handed back to the materialized `convert` rather than fabricated mid-pass.
- **Other recovery-needing conversions** (a fabricative required field, a `split_all` fan-out, a
  constraint subset against a PARTIAL target) still fall back to the materialized `convert`, whose
  peak *is* `∝ frame_count`.
- **Validation** on the streaming path is itself chunk-aware (`validation.streaming.validate_stream`,
  M12 deliverable 4): the expected object is re-read and filtered on the fly, the output is re-parsed
  as a stream, and the two are diffed frame-pairwise — so validation holds one frame pair resident
  and `convert_stream` stays sub-linear end to end. It produces the byte-identical `ValidationReport`
  the batch engine would (standing rule 3).

## Measured validation (M12/M13 proof fixtures)

`tests/streaming/test_streaming_memory.py` is the milestone's go/no-go gate. It generates a
deterministic synthetic trajectory (`tests/streaming/_generators.py`) and converts it two ways — the
streaming path and whole-file materialization — measuring the **peak Python-heap memory each
conversion itself allocates** with `tracemalloc`. `tracemalloc.reset_peak()` is called after imports
and fixture generation, so the number reflects the conversion's own allocations, not the
interpreter+imports floor. The same format-generic helpers back both the M12 extXYZ→extXYZ
pass-through and the M13 XDATCAR→extXYZ proof.

Representative run (2,500 frames × 50 atoms, ~9 MB source), **extXYZ → extXYZ**:

| Mode | Peak traced (conversion only) |
|---|---|
| **streaming** parse → export | **~1.6 MB** (one frame resident) |
| whole-file parse → export | ~91 MB |

**M13 — XDATCAR → extXYZ:** the honest gate, since 10⁴ configurations is an XDATCAR's ordinary size,
not a stress case (which is why the roadmap put chunking before this parser).

| Mode | Peak traced (conversion only) |
|---|---|
| **streaming** parse → export | **~0.2 MB** (one frame resident) |
| whole-file parse → export | ~47 MB |

The streaming path's footprint is a small **single-digit-percent** fraction of the materialized
path's on the same input — the sub-linear-in-frames property made numeric — and it stays flat as
`frame_count` grows while materialization rises linearly. Both paths produce **byte-identical
output** (the test asserts this): chunking changes memory, never bytes (standing rule 3).

**Why `tracemalloc`, not peak RSS.** An earlier form of this gate compared `ru_maxrss` between
subprocesses. `ru_maxrss` is a whole-process high-water mark that never falls, so it also folds in
the *import* transient — and on Linux/glibc the scientific stack (numpy + ASE + pydantic) peaks well
above 150 MB while importing and never releases it back to the high-water mark. A conversion whose
own footprint is real but smaller than that import transient (XDATCAR materialize, ≈47 MB) then
showed up as a **zero** delta, because its allocations reused pages already counted at import: the
gate became silently input-dependent, passing the extXYZ proof (≈91 MB, clears the floor) while the
XDATCAR proof collapsed to `material_delta == 0`. `reset_peak` discards the import high-water mark,
so the two paths separate by ~50–200× on every platform. `tracemalloc` traces the Python heap (the
`Frame`/`AtomsBlock`/`Cell` objects the streaming path avoids holding all at once) but not numpy's C
data buffers; those grow with frame count in the same direction, so excluding them makes the
demonstrated contrast a conservative lower bound, never an overstatement. The two assertions are then
(1) materialization clears a generous tens-of-MB floor (it holds the whole trajectory) and (2)
streaming is at most a quarter of it — both loose relative to the observed gap, so the gate is robust
to noise while still failing loudly if streaming ever regresses to materialize-then-write.
