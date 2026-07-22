"""Vendor a Crystallography Open Database entry into the real-world corpus (D70).

    python tests/wild/_fetch_cod.py 1000041 --case nacl-cubic-full-ops \\
        --why "legacy _symmetry_* tag spelling with a complete 192-operation loop"

Downloads the entry, writes it under ``tests/wild/cod/<case>/``, and prints a manifest
**stub** with the source hash and the issue codes the parser actually produced today.

The stub is a starting point, never the answer. M20's rule is that every anomaly a real file
raises is triaged by a human — so the printed ``issue_codes`` must be *read*, understood, and
either accepted into the manifest with a written note or fixed in the parser. A script that
wrote the manifest itself would launder "whatever the code does" into "what the file means",
which is the exact failure the wild corpus exists to prevent. Hence: it prints, you commit.

Files are vendored, not fetched at test time. A suite that reaches the network is a suite that
fails when a database is down, and a corpus whose contents can change under it is not a
regression corpus at all.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

COD_URL = "https://www.crystallography.net/cod/{cod_id}.cif"
WILD_COD_ROOT = Path(__file__).parent / "cod"


def fetch(cod_id: str) -> bytes:
    url = COD_URL.format(cod_id=cod_id)
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
        payload: bytes = response.read()
    return payload


def observed_issue_codes(path: Path) -> tuple[list[str], str | None]:
    """The issue codes the parser produces today, or the code it refuses with.

    Imported lazily so the fetch half of this script works in a checkout where the package
    is not installed."""
    from xtalate.parsers.cif import make_cif_parser
    from xtalate.sdk import ParseError

    parser = make_cif_parser()
    try:
        with path.open("rb") as fh:
            result = parser.parse(fh, filename=path.name)
    except ParseError as exc:
        errors = sorted(i.code for i in exc.issues if i.severity == "error")
        return [], errors[0] if errors else None
    return sorted(issue.code for issue in result.issues), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cod_id", help="COD entry number, e.g. 1000041")
    parser.add_argument("--case", required=True, help="corpus case directory name (kebab-case)")
    parser.add_argument("--why", required=True, help="what this entry is in the corpus to exercise")
    args = parser.parse_args(argv)

    directory = WILD_COD_ROOT / args.case
    directory.mkdir(parents=True, exist_ok=True)
    source_name = f"cod-{args.cod_id}.cif"
    source_path = directory / source_name
    payload = fetch(args.cod_id)
    source_path.write_bytes(payload)

    codes, refusal = observed_issue_codes(source_path)
    expectation = (
        f"  parse_error: {refusal}"
        if refusal
        else "  issue_codes:\n" + ("\n".join(f"    - {c}" for c in codes) or "    []")
    )

    print(f"# wrote {source_path} ({len(payload)} bytes)")
    print(f"# --- manifest stub for {directory / 'manifest.yaml'} — TRIAGE BEFORE COMMITTING ---")
    print(
        f"""case: {args.case}
format_id: cif
source_file: {source_name}
sha256: "{hashlib.sha256(payload).hexdigest()}"
origin:
  kind: published-dataset
  source: "Crystallography Open Database entry {args.cod_id}"
  url: "{COD_URL.format(cod_id=args.cod_id)}"
  license: "CC0-1.0"
expectation:
{expectation}
  stoichiometry: checked
notes: >-
  {args.why}"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
