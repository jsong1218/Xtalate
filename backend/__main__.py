"""``python -m backend`` — run the service with uvicorn for local development.

A convenience launcher only; the Tier 1 image (M25) invokes uvicorn directly. Host/port/reload are
read from the environment (``XTALATE_`` prefix) so this needs no arguments. Production process
management (workers, timeouts) is the container's job, not this module's.
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "backend.asgi:app",
        host=os.environ.get("XTALATE_HOST", "127.0.0.1"),
        port=int(os.environ.get("XTALATE_PORT", "8000")),
        reload=os.environ.get("XTALATE_RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()
