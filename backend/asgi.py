"""ASGI entry point: ``uvicorn backend.asgi:app`` (MASTER_SPEC Part 9 §2).

A single module-level ``app`` built from the environment, for the process an ASGI server runs. The
worker (M22) is a *second entrypoint on the same image* — one artifact, no API/worker version skew
(Part 9 §2) — so this module stays deliberately minimal: it only constructs the app the factory
already fully wires.
"""

from __future__ import annotations

from backend.app import create_app

app = create_app()
