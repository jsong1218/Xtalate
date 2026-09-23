#!/bin/bash -eu
# ClusterFuzzLite build script for the Atheris fuzzers (v2.0 review, S7).
# Runs inside the base-builder-python image (see Dockerfile). $SRC, $OUT, and compile_python_fuzzer
# are provided by that image.

# Install the pure library (no service/dev extras — the fuzzers only touch parsers + discovery).
pip3 install "$SRC/xtalate"

# Compile each harness into a self-contained libFuzzer binary named after the script basename.
# The harnesses import xtalate.parsers -> ase -> numpy/scipy, and PyInstaller's bundled hooks do
# not collect these packages' dynamically-imported C-extension submodules (numpy 2.x's
# `numpy._core`, scipy's `scipy._cyutility`, reached transitively via `ase.dft`) nor ase's data
# files, so the frozen binary crashes at startup ("No module named 'numpy._core._exceptions'",
# then "scipy install ... seems broken") and `bad_build_check` rejects it. `--collect-all`
# (forwarded to PyInstaller by compile_python_fuzzer) pulls each package's submodules, data,
# binaries, and metadata in whole; the full set is verified by freezing the harness import surface.
pyinstaller_collect="--collect-all=numpy --collect-all=scipy --collect-all=ase"
compile_python_fuzzer "$SRC/xtalate/tests/fuzz/fuzz_parsers.py" $pyinstaller_collect
compile_python_fuzzer "$SRC/xtalate/tests/fuzz/fuzz_discovery.py" $pyinstaller_collect

# Materialize the reviewable seed battery and ship it as each fuzzer's seed corpus. Both harnesses
# accept the same selector-byte-prefixed bytes, so they share one corpus. ClusterFuzzLite unpacks
# <fuzzer_basename>_seed_corpus.zip beside each binary.
seeds="$SRC/xtalate-seeds"
python3 "$SRC/xtalate/tests/fuzz/make_seed_corpus.py" "$seeds"
(cd "$seeds" && zip -q -r "$OUT/fuzz_parsers_seed_corpus.zip" .)
cp "$OUT/fuzz_parsers_seed_corpus.zip" "$OUT/fuzz_discovery_seed_corpus.zip"
