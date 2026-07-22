"""Persistence adapters — stateful backends behind interfaces Tier 0 can still satisfy.

The rule of MASTER_SPEC Part 9 §1.1: every stateful dependency has **two** backends behind **one**
interface — a Tier 0 backend that needs no services (a parser bug fix must never require Docker)
and a Tier 1 backend for the real deployment. This package holds the object-storage half (v0.5 M21
slice 2): the :class:`~backend.storage.objects.ObjectStore` interface with a filesystem backend
(Tier 0) and an S3-compatible backend (MinIO in Tier 1). The relational/database half arrives in
slice 3. Parity between the two backends of an interface is asserted by one test suite run against
both — parity is a test, not a hope.
"""

from __future__ import annotations

from backend.storage.objects import (
    ObjectNotFound,
    ObjectStore,
    StoredObject,
    create_object_store,
)

__all__ = [
    "ObjectNotFound",
    "ObjectStore",
    "StoredObject",
    "create_object_store",
]
