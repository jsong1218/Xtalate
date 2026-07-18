"""xtalate-toyfmt — a minimal example third-party Xtalate plugin (M16B discovery proof).

Not a shipped package. Installed only in CI (and on demand locally) so the entry-point
discovery pass in :mod:`xtalate.registry` runs against a real installed distribution, not just
the in-memory fakes of the M16A unit tests. It implements one trivial, self-describing text
format — ``toyfmt`` — through the public plugin SDK alone, and so also serves as the worked
packaging example the M16C contributor docs reference.
"""

from __future__ import annotations

from xtalate_toyfmt.exporter import ToyfmtExporter
from xtalate_toyfmt.parser import ToyfmtParser

__all__ = ["ToyfmtExporter", "ToyfmtParser"]
