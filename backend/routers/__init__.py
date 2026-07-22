"""The v0.5 API routers — one module per resource, all mounted under ``/v1`` (Part 6 §1).

M21 mounts the three *stateless* routers: :mod:`~backend.routers.health`,
:mod:`~backend.routers.capabilities`, and :mod:`~backend.routers.limits`. The job, upload,
download, and recovery routers arrive with their milestones (M22–M24) and mount the same way,
so the surface grows by addition, never by reshaping what M21 established.
"""

from __future__ import annotations
