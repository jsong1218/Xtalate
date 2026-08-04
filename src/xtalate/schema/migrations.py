"""Forward migration of persisted Canonical Objects across schema versions (Part 2 §5, Part 8 §3.3).

The Canonical Model is versioned (``schema_version``, §5). Until v1.0 it was a single pre-1.0
version and every object on disk was authored against it, so "load through the migration chain"
was the identity. The v1.0 **contract freeze** (M35) is the first real version transition:
``0.1.0 → 1.0.0``. This module is the registry the freeze needs — a mapping from a source version
to the function that carries an object one step forward — and the ``load_canonical`` entry point
that runs the chain and stamps the transition into Provenance.

Two rules shape the design:

* **Operate on the raw mapping, validate once at the end.** A migration *moves* data between
  fields — the ``0.1.0 → 1.0.0`` step lifts occupancy out of a namespaced carry-through into the
  new first-class ``atoms.occupancies`` field (D114). Doing that on a validated model would mean
  round-tripping through ``model_copy`` for every moved key; doing it on the decoded ``dict`` is
  direct, and the single ``model_validate`` at the end is the one place the result is checked
  against the *current* schema. A migration that produced an invalid object fails loudly there.

* **The migration is recorded, never silent (P1, §3.9).** A migrated object gains exactly one
  ``ConversionRecord(operation="migrate")`` naming the version transition and what moved, so a
  reader can see that the bytes they loaded were authored against an older schema and how the load
  reshaped them. A no-op load (already current) appends nothing.

Import position: this is ``schema`` code, so it may import only the bottom-layer cross-cutting
utilities (``xtalate._time`` for the timestamp, the package ``__version__`` for the record's
``tool_version``) — the same two the parsers' ``_common`` provenance helper uses. It never reaches
up into a parser or the conversion engine (P2, the import-linter layers contract).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from xtalate import __version__
from xtalate._time import utc_now
from xtalate.schema.models import SCHEMA_VERSION, CanonicalObject, ConversionRecord

# A migration step: given the decoded object mapping at some version, return the mapping carried to
# the next version plus zero or more plain-language notes describing what it moved (folded into the
# single migrate record's assumptions). A step never stamps ``schema_version`` or the record — the
# chain runner owns both, so a step cannot lie about the version it produced.
_Step = tuple[str, Callable[[dict[str, Any]], tuple[dict[str, Any], list[str]]]]


class MigrationError(ValueError):
    """A persisted object cannot be carried forward to the current schema.

    Raised when the object declares no ``schema_version`` at all (nothing to migrate *from*), or
    when its version has no registered path to the current one — a stored object authored against
    a schema this build does not know how to read. Both are load-time failures, not silent
    defaults."""


# --- the 0.1.0 -> 1.0.0 step (M35 / D114) -------------------------------------------------------

# The pre-1.0 spelling of partial site occupancy: a per-atom carry-through column under the CIF
# namespace, un-modelled by the schema (Part 3 §3 n.11). The v1.0 freeze promotes it to the
# first-class ``atoms.occupancies`` field, so a 0.1.0 object still carrying the old key is moved.
_LEGACY_OCCUPANCY_KEY = "cif:occupancy"


def _promote_occupancy(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Lift ``user_metadata.custom_per_atom['cif:occupancy']`` into ``atoms.occupancies`` (D114).

    The carry-through lived at object level (its first dimension is the atom count, applying to
    every frame — Part 2 §3.10), so it is written onto every frame's ``atoms`` block; CIF is
    single-structure in practice, so that is one frame, but the general rule is the honest one. An
    object with no such key (every format but pre-1.0 CIF, and any CIF without occupancy) is
    untouched and the step is a version-stamp-only no-op for it."""
    user_metadata = data.get("user_metadata")
    if not isinstance(user_metadata, dict):
        return data, []
    custom_per_atom = user_metadata.get("custom_per_atom")
    if not isinstance(custom_per_atom, dict) or _LEGACY_OCCUPANCY_KEY not in custom_per_atom:
        return data, []

    occupancy = list(custom_per_atom.pop(_LEGACY_OCCUPANCY_KEY))
    for frame in data.get("frames", []):
        atoms = frame.get("atoms")
        if isinstance(atoms, dict):
            atoms["occupancies"] = list(occupancy)
    note = (
        f"Promoted user_metadata.custom_per_atom['{_LEGACY_OCCUPANCY_KEY}'] to "
        f"atoms.occupancies for {len(occupancy)} atom(s)."
    )
    return data, [note]


# The registry: source version -> (target version, step). Composed by ``migrate`` into a chain that
# runs until the object reaches ``SCHEMA_VERSION``. A future 1.0.0 -> 2.0.0 step is a new entry
# here; the runner needs no change.
_MIGRATIONS: dict[str, _Step] = {
    "0.1.0": ("1.0.0", _promote_occupancy),
}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Carry a decoded Canonical Object mapping forward to the current schema version.

    Runs the registered chain from the object's declared ``schema_version`` up to
    ``SCHEMA_VERSION``, stamping the version at each step and appending exactly one
    ``operation="migrate"`` provenance record for the whole transition (none if already current).
    Does not validate — that is ``load_canonical``'s single final step. The input mapping is not
    mutated; a deep copy is migrated and returned.

    Raises ``MigrationError`` if the object declares no version, or if some version in the chain has
    no registered successor (a schema this build cannot read forward)."""
    data = copy.deepcopy(data)
    origin = data.get("schema_version")
    if not isinstance(origin, str):
        raise MigrationError(
            "canonical object declares no schema_version — cannot place it on the migration chain"
        )

    version = origin
    notes: list[str] = []
    while version != SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise MigrationError(
                f"no migration path from schema {version!r} to current {SCHEMA_VERSION!r}"
            )
        target, transform = step
        data, step_notes = transform(data)
        data["schema_version"] = target
        notes.extend(step_notes)
        version = target

    if version != origin:
        _append_migrate_record(data, origin, notes)
    return data


def _append_migrate_record(data: dict[str, Any], origin: str, notes: list[str]) -> None:
    """Append the single migrate record to the object's history (§3.9, append-only).

    Built through ``ConversionRecord`` (not a hand-written dict) so the record can never drift from
    the model's field set, then dumped back to JSON-shaped data for the final ``model_validate``."""
    record = ConversionRecord(
        timestamp=utc_now(),
        operation="migrate",
        source_format=None,
        target_format=None,
        tool_version=__version__,
        parser_version=None,
        assumptions=[f"Migrated canonical schema {origin} → {SCHEMA_VERSION}.", *notes],
    )
    provenance = data.setdefault("provenance", {})
    history = provenance.setdefault("history", [])
    history.append(record.model_dump(mode="json"))


def load_canonical(source: str | bytes | dict[str, Any]) -> CanonicalObject:
    """Load a persisted Canonical Object, migrating it to the current schema first (Part 8 §3.3).

    ``source`` is JSON text/bytes or an already-decoded mapping. This is the one seam through which
    stored objects re-enter memory: it runs the migration chain, then validates the result against
    the current models exactly once. A same-version object migrates trivially (validation only, no
    record); an older object is carried forward and stamped."""
    data = json.loads(source) if isinstance(source, str | bytes | bytearray) else source
    return CanonicalObject.model_validate(migrate(data))
