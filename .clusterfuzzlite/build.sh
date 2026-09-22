#!/bin/bash -eu
# ClusterFuzzLite build script for the Atheris fuzzers (v2.0 review, S7).
# Runs inside the base-builder-python image (see Dockerfile). $SRC, $OUT, and compile_python_fuzzer
# are provided by that image.

# Install the pure library (no service/dev extras — the fuzzers only touch parsers + discovery).
pip3 install "$SRC/xtalate"

# Compile each harness into a self-contained libFuzzer binary named after the script basename.
compile_python_fuzzer "$SRC/xtalate/tests/fuzz/fuzz_parsers.py"
compile_python_fuzzer "$SRC/xtalate/tests/fuzz/fuzz_discovery.py"

# Materialize the reviewable seed battery and ship it as each fuzzer's seed corpus. Both harnesses
# accept the same selector-byte-prefixed bytes, so they share one corpus. ClusterFuzzLite unpacks
# <fuzzer_basename>_seed_corpus.zip beside each binary.
seeds="$SRC/xtalate-seeds"
python3 "$SRC/xtalate/tests/fuzz/make_seed_corpus.py" "$seeds"
(cd "$seeds" && zip -q -r "$OUT/fuzz_parsers_seed_corpus.zip" .)
cp "$OUT/fuzz_parsers_seed_corpus.zip" "$OUT/fuzz_discovery_seed_corpus.zip"
