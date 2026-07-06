"""Conversion Engine — orchestrates parse → capability diff → recovery → export → report.

Owns the pre-flight diff, the ``write_plan``, the ``ConversionReport`` (Part 4 §2),
the completeness-invariant runtime assertion (review §4.5), and the automatic
final-step validation (Part 1 §3). Delegates all format and recovery logic.
Populated in M4-M5.
"""
