"""The analysis runner — invoke an ``AnalysisPlugin`` and merge its namespaced results.

Analysis *reads* a Canonical Object and *annotates its own namespace*; it is never a conversion
step (Part 0 §3.2, Part 2 §6). This module is where v1.8 M68's two structural guarantees are made
literal:

* **Containment is enforced, not trusted (D268).** The plugin is handed a **deep copy**, so a
  mutation it makes cannot reach the caller's object; and only keys prefixed ``"<name>:"`` for the
  plugin's own ``name`` are merged into ``user_metadata.custom_global`` — Part 2 §6 rule 2's
  prefix, checked at write time. Any other key is an un-namespaced user key (reserved for end
  users and for parser carry-through), a canonical scientific path, or another plugin's
  namespace, and every one of them is a reported plugin error with the object returned untouched.
  The merge *drops* what it cannot place; nothing about the plugin's behaviour is trusted.
* **Every run is recorded (D269).** A ``ConversionRecord(operation="analyze")`` naming the plugin,
  its version, and the keys it wrote is appended to ``provenance.history``, so an annotated
  object's extras never appear from nowhere.

Results land in ``user_metadata.custom_global`` — Part 2 §6.1's destination for global, opaque
content the core carries but does not interpret — the container format carry-through already
routes to, so a reader who understands ``custom_global["xyz:comment"]`` already understands
``custom_global["rdf-analysis:g_of_r"]``. There is deliberately no separate ``analysis_results``
container, and no conversion-engine wiring: the core never *reads* a plugin namespace to change
engine behaviour (impl-plan §4 rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue, ValidationError

from xtalate import __version__
from xtalate._time import utc_now
from xtalate.schema import CanonicalObject, ConversionRecord, UserMetadata
from xtalate.sdk.plugins import AnalysisPlugin

__all__ = ["AnalysisError", "AnalysisRun", "run_analysis"]


@dataclass(frozen=True)
class AnalysisRun:
    """The result of one analysis run: the annotated object and the entries the plugin wrote.

    Both are needed and neither can be reconstructed from the other without re-introducing the bug
    this type exists to kill: ``entries`` is the plugin's own ``"<name>:"`` namespace *exactly as
    it produced it*, while ``canonical`` also carries any pre-existing carry-through the source
    happened to leave under the same prefix. A caller that wants "what did the plugin compute"
    reads ``entries``; a caller that wants "the object plus its annotation" reads ``canonical``.
    Rebuilding ``entries`` by prefix-scanning ``canonical.user_metadata.custom_global`` — the shape
    the runner and CLI used before v2.0 — mis-attributes such a colliding carry-through key as
    plugin output, so this type hands the exact set back rather than inviting the rescan.
    """

    canonical: CanonicalObject
    entries: dict[str, JsonValue]


class AnalysisError(ValueError):
    """An analysis plugin broke the containment contract, or crashed.

    Raised by :func:`run_analysis` when a plugin returns a key outside its own ``"<name>:"``
    namespace (D268), returns a value ``user_metadata`` cannot hold, or raises while analyzing.
    The message names the plugin (and, for a bad key, the offending key) so the failure points at
    the plugin rather than at Xtalate — the :class:`~xtalate.registry.PluginLoadError` discipline
    applied at run time. A plugin error is its **own** reported failure: the caller's object is
    returned untouched, and no ``"analyze"`` record is appended, because nothing was annotated.
    """


def run_analysis(canonical: CanonicalObject, plugin: AnalysisPlugin) -> AnalysisRun:
    """Run ``plugin`` against ``canonical`` and return an :class:`AnalysisRun`.

    ``AnalysisRun.canonical`` is a **new** object; the argument is never mutated, whatever the
    plugin does. It differs from the argument in exactly two places: the keys the plugin wrote,
    merged into ``user_metadata.custom_global``, and one appended ``"analyze"``
    ``ConversionRecord`` in ``provenance.history``. Frames, scientific fields, and every other
    ``user_metadata`` entry are untouched — analysis is annotation, never conversion (P5, P6).
    ``AnalysisRun.entries`` is the plugin's own contribution, returned verbatim so a caller reports
    *exactly* what the plugin computed rather than re-deriving it by prefix-scanning the merged
    ``custom_global`` (which would sweep in a colliding carry-through key — the v2.0 S6 fix).

    Raises :class:`AnalysisError` — leaving the argument untouched — when the plugin escapes its
    namespace, returns an unserializable value, or raises.
    """
    results = _invoke(canonical, plugin)
    entries = _contained_entries(plugin, results)
    _check_container_accepts(plugin, entries)
    record = _analyze_record(canonical, plugin, keys=sorted(entries))
    annotated = canonical.model_copy(
        update={
            "user_metadata": canonical.user_metadata.model_copy(
                update={"custom_global": {**canonical.user_metadata.custom_global, **entries}}
            ),
            "provenance": canonical.provenance.model_copy(
                update={"history": [*canonical.provenance.history, record]}
            ),
        }
    )
    return AnalysisRun(canonical=annotated, entries=entries)


def _invoke(canonical: CanonicalObject, plugin: AnalysisPlugin) -> Mapping[str, JsonValue]:
    """Call ``plugin.analyze`` on a deep copy of ``canonical``.

    The copy is the read-only view: a plugin that mutates its argument writes into a throwaway
    tree, so the caller's object is untouched **by construction** rather than by a post-hoc
    mutation check that would have to guess what to compare. The cost is one deep copy per run,
    which is the price of enforcing the rule instead of documenting it (D268). A plugin that
    raises is reported as an :class:`AnalysisError` naming it — the discovery phase's
    ``PluginLoadError`` discipline, applied at run time.
    """
    view = canonical.model_copy(deep=True)
    try:
        return plugin.analyze(view)
    except Exception as exc:
        raise AnalysisError(
            f"analysis plugin {plugin.name!r} ({plugin.version}) raised {type(exc).__name__}: {exc}"
        ) from exc


def _contained_entries(
    plugin: AnalysisPlugin, results: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    """The plugin's results, rejected wholesale if any key escapes its namespace (D268).

    Checked *before* anything is merged, so no partial annotation can exist: a plugin that writes
    one legal key and one illegal one is an error, not a half-merge.
    """
    prefix = f"{plugin.name}:"
    entries = dict(results)
    foreign = sorted(key for key in entries if not key.startswith(prefix))
    if foreign:
        raise AnalysisError(
            f"analysis plugin {plugin.name!r} ({plugin.version}) returned key(s) outside its "
            f"{prefix!r} namespace: {', '.join(foreign)!r} — a plugin writes only its own "
            "namespace, and un-namespaced keys are reserved for end users and parser "
            "carry-through (Part 2 §6 rule 2); the object is left untouched"
        )
    return entries


def _check_container_accepts(plugin: AnalysisPlugin, entries: dict[str, JsonValue]) -> None:
    """Validate the plugin's values against ``custom_global``'s declared type before merging.

    ``model_copy`` does not validate its update, so a value the container cannot hold would
    otherwise enter the object here and surface much later — at serialization time, far from the
    plugin that produced it. Validating a throwaway ``UserMetadata`` checks the plugin's values
    alone against the same ``JsonValue`` declaration an ordinary carry-through gets (§6 rule 1:
    shape-validated and serializability-checked, semantics-free), without re-validating content
    the object already held.
    """
    try:
        UserMetadata(custom_global=entries)
    except ValidationError as exc:
        raise AnalysisError(
            f"analysis plugin {plugin.name!r} ({plugin.version}) returned a value "
            f"user_metadata cannot hold: {exc}"
        ) from exc


def _analyze_record(
    canonical: CanonicalObject, plugin: AnalysisPlugin, *, keys: list[str]
) -> ConversionRecord:
    """The single ``operation="analyze"`` history entry one analysis run appends (D269).

    ``parser_version`` carries the plugin's identity (``"<name> <version>"``) — the field's
    documented job is naming the specific plugin used, and an analysis plugin is the plugin this
    operation used — while ``assumptions`` carries the human-readable statement of what it did,
    including the keys it wrote (sorted, so the record is deterministic). ``target_format`` is
    ``None``: analysis produces no converted artifact. The reserved operation value ``"analyze"``
    is documented at ``schema/models.py`` (Part 2 §3.9) — a ``str`` field gaining a documented
    value, which is why the schema stays ``1.0.0``.
    """
    written = ", ".join(keys) if keys else "no keys"
    return ConversionRecord(
        timestamp=utc_now(),
        operation="analyze",
        source_format=canonical.provenance.source_format,
        target_format=None,
        tool_version=__version__,
        parser_version=f"{plugin.name} {plugin.version}",
        assumptions=[
            f"analysis plugin {plugin.name!r} {plugin.version} wrote custom_global: {written}"
        ],
    )
