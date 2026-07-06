"""ChemBridge CLI — a thin presenter over the engines (MASTER_SPEC Appendix A).

Contains no scientific logic; emits the report schemas of Parts 3-5 verbatim as
JSON and honors the preset-only recovery model (Part 10 §2). Commands
(``inspect``/``convert``/``validate``/``capabilities``) are populated in M6.
"""


def main() -> int:
    """Console-script entry point (``chembridge``). Placeholder until M6."""
    print(
        "chembridge 0.1.0.dev0 — CLI not yet implemented "
        "(see docs/IMPLEMENTATION_PLAN.md, milestone M6)."
    )
    return 0
