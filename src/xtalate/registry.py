"""``default_registry()`` — the standard first-party registry (MASTER_SPEC Part 3 §7.1).

A convenience factory that registers every built-in parser and exporter into one
:class:`~xtalate.capabilities.Registry`, so callers (the CLI, examples, and any embedder)
get the full v0.1 format set without hand-wiring it. This is the "explicit first-party
registration list" the spec calls sufficient before entry-point plugin discovery exists
(Part 3 §7.1); third-party plugins attach at the same registry via ``importlib.metadata``
entry points (**P6**; v0.3, M16A).

Lives at the package root, not in ``capabilities``: the registry *machinery* must not depend on
the concrete parsers/exporters (that would invert the import graph), so the wiring that pulls
them together sits above both — the same reason the CLI, not the engine, composes the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import EntryPoint, entry_points
from typing import TypeVar

from xtalate.capabilities import InvalidCapabilityDeclaration, Registry
from xtalate.exporters import builtin_exporters
from xtalate.parsers import builtin_parsers
from xtalate.sdk import ExporterPlugin, ParserPlugin

# Entry-point group names third-party distributions advertise their plugins under
# (MASTER_SPEC Part 3 §7.1). Stable public strings — renaming them breaks every installed
# plugin — so they live here as named constants, not inline literals.
PARSER_ENTRY_POINT_GROUP = "xtalate.parsers"
EXPORTER_ENTRY_POINT_GROUP = "xtalate.exporters"


class PluginLoadError(RuntimeError):
    """A third-party entry point could not be loaded or instantiated.

    Raised when ``EntryPoint.load()`` or the loaded factory raises — an installed plugin whose
    module fails to import, or whose class/factory raises on construction — and when a plugin's
    ``format_id`` collides with an already-registered format (the registry's duplicate guard,
    re-raised here so the message names the offending entry point). The message names the entry
    point (group, name, and ``module:attr`` target) so the failure points at the plugin, not at
    Xtalate. A plugin whose *capability declaration* is malformed fails differently and just as
    loudly — ``InvalidCapabilityDeclaration`` from ``register_parser``/``register_exporter``
    propagates unwrapped, since it already names the format and the defect. Discovery never
    swallows a broken plugin (Part 3 §7.1: "rejected with a readable error ... fails loudly").
    """


def default_registry() -> Registry:
    """A fresh :class:`Registry` with all built-in parsers and exporters registered,
    followed by any third-party plugins advertised via entry points (Part 3 §7.1).

    First-party formats register first, so their ids win the namespace; a colliding third-party
    ``format_id`` then hits the registry's duplicate guard and is rejected. Discovery is purely
    *additive* — the built-in lists stay explicit (**P6**), and an installation with no plugins
    behaves exactly as before the mechanism existed.
    """
    registry = Registry()
    for parser in builtin_parsers():
        registry.register_parser(parser)
    for exporter in builtin_exporters():
        registry.register_exporter(exporter)
    _register_from_entry_points(registry)
    return registry


def _register_from_entry_points(registry: Registry) -> None:
    """Discover and register every parser/exporter advertised under the Xtalate entry-point
    groups. Each plugin passes through the *same* ``register_*`` path as a built-in, so it gets
    duplicate detection and capability-declaration validation for free (Part 3 §7.1).

    The kind check (``isinstance``) lives here, where the expected type is statically known per
    group, so a target that loads but yields the wrong kind of object is rejected before it can
    blow up obscurely deep inside ``register_*``.
    """
    for ep in entry_points(group=PARSER_ENTRY_POINT_GROUP):
        plugin = _load_plugin(ep)
        if not isinstance(plugin, ParserPlugin):
            raise PluginLoadError(
                f"{_describe(ep)} produced {type(plugin).__name__}, not a ParserPlugin"
            )
        _register(registry.register_parser, plugin, ep)
    for ep in entry_points(group=EXPORTER_ENTRY_POINT_GROUP):
        plugin = _load_plugin(ep)
        if not isinstance(plugin, ExporterPlugin):
            raise PluginLoadError(
                f"{_describe(ep)} produced {type(plugin).__name__}, not an ExporterPlugin"
            )
        _register(registry.register_exporter, plugin, ep)


_P = TypeVar("_P", ParserPlugin, ExporterPlugin)


def _register(register: Callable[[_P], None], plugin: _P, ep: EntryPoint) -> None:
    """Register one discovered plugin, attributing a duplicate-``format_id`` rejection to its
    entry point. The registry's duplicate guard raises a bare ``ValueError`` that names only the
    format — enough for first-party registration (the colliding line of code is in this repo),
    but a discovered collision needs the *distribution* named to be actionable, so it is
    re-raised as ``PluginLoadError`` with the entry-point identity. A malformed declaration
    (``InvalidCapabilityDeclaration``, a ``ValueError`` subclass) already names the format and
    the defect, so it propagates unwrapped."""
    try:
        register(plugin)
    except InvalidCapabilityDeclaration:
        raise
    except ValueError as exc:
        raise PluginLoadError(f"{_describe(ep)}: {exc}") from exc


def _load_plugin(ep: EntryPoint) -> object:
    """Load one entry point and instantiate the plugin it points at.

    An entry point targets a callable — a plugin class or a factory returning an instance,
    exactly like the built-in ``XyzParser`` / ``make_poscar_parser`` pair — so it is loaded and
    then *called*. Any failure to import or construct is re-raised as :class:`PluginLoadError`
    naming the entry point; the caller checks the object is the right *kind* of plugin.
    """
    try:
        factory = ep.load()
        return factory()
    except Exception as exc:
        raise PluginLoadError(f"{_describe(ep)} failed to load: {exc}") from exc


def _describe(ep: EntryPoint) -> str:
    """A human-readable identity for an entry point, for error messages: its group, name, and
    ``module:attr`` target — enough to find the offending declaration in a plugin's metadata."""
    return f"entry point {ep.group}:{ep.name} = {ep.value!r}"
