# Xtalate — Memory Ceiling (streaming core)

> **Status.** Introduced with M12 (v0.3, "Trajectories at Scale"), the frame-chunked processing
> core. This note states the memory model the streaming path guarantees and records its measured
> validation. The numbers here are seeded from M12's proof fixture; M15 finalizes them against the
> full synthetic performance corpus (`docs/IMPLEMENTATION_PLAN_v0.3.md` M15 deliverable 4).

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

- **Recovery-needing conversions** (a target with a frame cap or a recovery-able required field,
  e.g. `→ POSCAR`) fall back to the materialized `convert`, whose peak *is* `∝ frame_count`. Making
  the recovery interplay chunk-aware (`frame_selection` single-pass, `bounding_box` on the selected
  frame) lands with M13's XDATCAR, the format that exercises it (DECISIONS.md D56).
- **Validation** on the streaming path is itself chunk-aware (`validation.streaming.validate_stream`,
  M12 deliverable 4): the expected object is re-read and filtered on the fly, the output is re-parsed
  as a stream, and the two are diffed frame-pairwise — so validation holds one frame pair resident
  and `convert_stream` stays sub-linear end to end. It produces the byte-identical `ValidationReport`
  the batch engine would (standing rule 3).

## Measured validation (M12 proof fixture)

`tests/streaming/test_streaming_memory.py` is the milestone's go/no-go gate. It generates a
deterministic synthetic extXYZ trajectory (`tests/streaming/_generators.py`) and converts it in two
subprocesses — the streaming path and whole-file materialization — measuring each process's peak
RSS (`ru_maxrss`, normalized across platforms). A baseline subprocess isolates the
interpreter+imports floor.

Representative local run (2,500 frames × 50 atoms, ~9 MB source; macOS):

| Mode | Peak RSS | Trajectory-attributable (peak − baseline) |
|---|---|---|
| baseline (imports only) | ~83 MB | — |
| **streaming** parse → export | ~86 MB | **~3 MB** |
| whole-file parse → export | ~207 MB | ~123 MB |

The streaming path's trajectory-attributable memory is a small **single-digit-percent** fraction of
the materialized path's on the same input — the sub-linear-in-frames property made numeric. Both
paths produce **byte-identical output** (the test asserts this): chunking changes memory, never
bytes (standing rule 3).

The gate compares **deltas over the interpreter+imports baseline**, not absolute peaks: on shared CI
runners that baseline (~150 MB) dominates the peak, so the streaming path can add ~0 measurable RSS
while materialization adds tens of MB, yet the two *absolute* peaks then sit within ~25% of each
other — an absolute-peak ratio would falsely fail. The two assertions are therefore (1)
materialization's delta clears a generous tens-of-MB floor (it holds the whole trajectory) and (2)
streaming's delta is at most half of it. Both are deliberately loose relative to the observed gap, so
the gate is robust to CI noise while still failing loudly if streaming ever regresses to
materialize-then-write (which would push its delta up toward materialization's).
