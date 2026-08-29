# Attributions

Xtalate itself is licensed under the **Apache License, Version 2.0** (see [`LICENSE`](LICENSE)
and [`NOTICE`](NOTICE)). This file records the third-party software Xtalate **depends on** — the
runtime dependencies a `pip install` pulls in — with each dependency's license, so the obligations
those licenses carry can never silently lapse.

> **Two attribution files, two scopes — do not confuse them.**
> - **This file (`ATTRIBUTIONS.md`, project root)** covers the **software dependencies** Xtalate
>   installs and runs against (the Python distributions below, and the frontend's npm tree).
> - **[`tests/golden/ATTRIBUTIONS.md`](tests/golden/ATTRIBUTIONS.md)** covers the **test *data*** —
>   every file in the golden (`tests/golden/`) and real-world (`tests/wild/`) corpora, with its
>   per-fixture license and provenance. That file is **generated** from the per-fixture
>   `manifest.yaml` files and diffed in CI; the third-party data it aggregates (the Crystallography
>   Open Database corpus, CC0-1.0) is also surfaced in [`NOTICE`](NOTICE).
>
> **CI-enforced.** A completeness test (`tests/test_attributions.py`) fails if any distribution
> declared in `pyproject.toml` — the core `[project].dependencies` or the `service` optional
> extra — is missing from the tables below. The file cannot drift silently behind the dependency
> set. Version columns show the **declared floor** from `pyproject.toml`, not whatever a resolver
> happens to pin; licenses are the upstream projects' own declarations (SPDX identifiers).

## Core runtime dependencies (`pip install xtalate`)

The pure library + CLI. Kept deliberately small (`docs/private/DECISIONS.md` D4/D7): four
dependencies, including one secure XML parser and the sole scientific-I/O workhorse.

| Distribution | Declared floor | License (SPDX) |
|---|---|---|
| [pydantic](https://github.com/pydantic/pydantic) | `>=2.7` | MIT |
| [numpy](https://github.com/numpy/numpy) | `>=1.26` | BSD-3-Clause (with bundled 0BSD / MIT / Zlib / CC0-1.0 components) |
| [ase](https://gitlab.com/ase/ase) | `>=3.29,<4` | LGPL-2.1-or-later |
| [PyYAML](https://github.com/yaml/pyyaml) | `>=6` | MIT |
| [defusedxml](https://github.com/tiran/defusedxml) | `>=0.7.1` | PSF-2.0 |

**defusedxml is the secure XML dependency** for the untrusted `vasprun.xml` parser; it runs in
library code before any optional service layer is involved. **ASE is the sole scientific dependency**
(`docs/private/DECISIONS.md` D7). It backs the extXYZ
parser/exporter and the ASE `.traj` format, and nothing else in the core reaches for it; pymatgen
was evaluated and rejected (D4/D7) to keep the dependency surface — and the attack/CVE surface
(risk R10) — minimal. ASE is **LGPL-2.1-or-later**: Xtalate imports it as an ordinary library
(dynamic use), which the LGPL permits without Xtalate's own Apache-2.0 licensing being affected;
Xtalate ships no modified copy of ASE.

## `service` optional dependencies (`pip install xtalate[service]`)

The v0.5 Service layer (FastAPI app + adapters). Held **out** of the core on purpose
(`docs/private/DECISIONS.md` D79): `pip install xtalate` stays the pure library + CLI, and a parser
fix must never require FastAPI. A deployment opts in with the `service` extra.

| Distribution | Declared floor | License (SPDX) |
|---|---|---|
| [fastapi](https://github.com/fastapi/fastapi) | `>=0.115` | MIT |
| [uvicorn](https://github.com/encode/uvicorn) (`[standard]`) | `>=0.30` | BSD-3-Clause |
| [pydantic-settings](https://github.com/pydantic/pydantic-settings) | `>=2.3` | MIT |
| [boto3](https://github.com/boto/boto3) | `>=1.34` | Apache-2.0 |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | `>=2.0` | MIT |
| [alembic](https://github.com/sqlalchemy/alembic) | `>=1.13` | MIT |
| [psycopg](https://github.com/psycopg/psycopg) (`[binary]`) | `>=3.1` | LGPL-3.0-only |
| [rq](https://github.com/rq/rq) | `>=1.16` | BSD-2-Clause |
| [redis](https://github.com/redis/redis-py) | `>=5.0` | MIT |
| [python-multipart](https://github.com/Kludex/python-multipart) | `>=0.0.9` | Apache-2.0 |

**psycopg is LGPL-3.0-only** — like ASE, it is used as an installed library (the PostgreSQL driver,
confined to the storage backend), which the LGPL permits; Xtalate distributes no modified copy. It
is an *optional* dependency: the Tier 0 SQLite backend (stdlib) needs no driver at all.

The `dev` extra (pytest, ruff, mypy, hypothesis, import-linter, pip-audit, the test HTTP transport,
and the `service` stack pulled in for typing/tests) ships **no runtime code** and is not attributed
here — it is not part of any installed or distributed artifact.

## Frontend (`frontend/`, the Web UI)

The v0.6 Next.js Web UI is a separate, non-published npm workspace (`frontend/package.json` sets
`"private": true`); it is **not** part of the `pip install xtalate` distribution and ships no code
into the Python package. Its dependency tree is the standard Next.js/React ecosystem — all
permissive (MIT / BSD / ISC / Apache-2.0 family). The authoritative, resolved provenance is the
committed lockfile [`frontend/package-lock.json`](frontend/package-lock.json); generate a full
per-package license report from it with any standard tool (e.g. `npx license-checker` /
`license-checker-rseidelsohn` against `frontend/node_modules`). Direct dependencies:

| Package | Declared range | License |
|---|---|---|
| next | `^15.0.0` | MIT |
| react / react-dom | `^18.3.1` | MIT |
| @tanstack/react-query | `^5.51.0` | MIT |
| openapi-fetch | `^0.11.0` | MIT |
| react-markdown | `^9.1.0` | MIT |
| remark-gfm | `^4.0.1` | MIT |
| rehype-slug | `^6.0.0` | MIT |
| molstar | `5.11.0` (pinned — the v1.6 M59-S2 geometry viewer, D233) | MIT |

## Test data

Third-party test **data** (as opposed to software) is attributed separately, because it carries its
own per-file provenance obligations:

- **[`tests/golden/ATTRIBUTIONS.md`](tests/golden/ATTRIBUTIONS.md)** — generated from the golden and
  wild corpora's `manifest.yaml` files, one entry per fixture. The synthetic fixtures are Xtalate's
  own work under Apache-2.0; the real-world CIF corpus is the Crystallography Open Database, used
  under CC0-1.0.
- **[`NOTICE`](NOTICE)** — the top-level attribution home the Apache-2.0 license points at, where
  the COD corpus attribution is surfaced.
