"""Capability Matrix — registry and query API over ``FormatCapabilities`` (Part 3 §4).

Assembles the capability declarations that plugins produce (the data model lives in
``sdk``) into a queryable registry; it is consumer, not owner, of that model, and
never executes format logic (Part 1 §2). Depends on ``schema`` and ``sdk``.
Implemented in M2.
"""

from xtalate.capabilities.registry import (
    CapabilityMatrix,
    InvalidCapabilityDeclaration,
    Registry,
)

__all__ = [
    "CapabilityMatrix",
    "InvalidCapabilityDeclaration",
    "Registry",
]
