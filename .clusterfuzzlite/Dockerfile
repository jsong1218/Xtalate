# ClusterFuzzLite build image for the Atheris fuzzers (v2.0 review, S7).
#
# base-builder-python is OSS-Fuzz's own continuously-rebuilt toolchain image: it bundles the
# Atheris + libFuzzer + coverage runtime that the ClusterFuzzLite GitHub Action expects, and the
# two must stay in lockstep. OSS-Fuzz builds ephemeral fuzzers against the *current* base image on
# every run, so digest-pinning it (as we pin python:3.13-slim in the app Dockerfiles) is explicitly
# discouraged here — a stale digest would drift out of sync with the runner. This is the one image
# in the repo referenced by tag on purpose; everything under our control stays SHA-pinned.
FROM gcr.io/oss-fuzz-base/base-builder-python

COPY . $SRC/xtalate
WORKDIR $SRC/xtalate
COPY .clusterfuzzlite/build.sh $SRC/
