"""Plugin registry and Capability Matrix (MASTER_SPEC Part 3 §4).

The registry owns the explicit list of registered parsers/exporters and the assembled
Capability Matrix; the *data model* it assembles lives in ``sdk`` (§4.1). Registration is
**explicit** — ``register_parser(...)`` / ``register_exporter(...)`` — not entry-point
discovery: that mechanism is only required once third-party plugins exist (§7.1, v0.3+),
and the interfaces are identical, so the switch later is a loading change, not a rewrite.

At registration the plugin's ``capabilities()`` declaration is validated against the
canonical schema paths and its wildcards expanded (§4.1): "the registry rejects
declarations with unknown paths ... which keeps the matrix and the schema from drifting."

**Analysis plugins (v1.8 M68, Part 2 §6).** The third plugin kind registers here too, keyed by
its namespace ``name`` rather than a ``format_id``: it declares no capabilities, holds no matrix
row, and is never a conversion source or target — so ``register_analysis_plugin`` can move the
format surface not at all, which is the structural half of "analysis is annotation, not
conversion". The run-time half lives in ``sdk.analysis`` (D268).

**Parser-only formats (read-only, v1.2 M42-S1, D159).** A ``ParserPlugin`` may register
with **no** paired ``ExporterPlugin`` — the parser-only seam every DFT-*output* format needs
(outputs of a code are never conversion targets). The matrix is keyed by
``(format_id, direction)``, so such a format naturally holds a read row and **no** write
row, and every conversion-target enumeration is derived from ``exporters()`` — a parser-only
id is included as a *source* and automatically absent as a *target*, so ``convert --to
<parser-only-fmt>`` refuses with the same unknown/unavailable-target error as an
unregistered id. Nothing downstream may assume a parser has a same-id exporter (round-trip
harnesses derive their targets from ``exporters()`` for exactly this reason).
"""

from __future__ import annotations

from xtalate.schema.paths import expand_capability_path, is_valid_path
from xtalate.sdk import (
    AnalysisPlugin,
    CapabilityLevel,
    ExporterPlugin,
    FieldCapability,
    FormatCapabilities,
    ParserPlugin,
)


class InvalidCapabilityDeclaration(ValueError):
    """A plugin declared a capability against an unknown canonical path, or a declaration
    inconsistent with the plugin registering it (mismatched id/direction)."""


def _validate_and_expand(
    caps: FormatCapabilities, *, expected_direction: str, expected_format_id: str
) -> FormatCapabilities:
    """Return a copy of ``caps`` with every wildcard ``fields`` key expanded to concrete
    leaf paths. Raises ``InvalidCapabilityDeclaration`` on any unknown path, a direction
    mismatch, or a declaration whose ``format_id`` is not the registering plugin's."""
    if caps.format_id != expected_format_id:
        raise InvalidCapabilityDeclaration(
            f"plugin {expected_format_id!r}: capabilities() declares format_id "
            f"{caps.format_id!r}; a declaration must carry the format_id of the plugin "
            "registering it"
        )
    if caps.direction != expected_direction:
        raise InvalidCapabilityDeclaration(
            f"{caps.format_id!r}: declared direction {caps.direction!r} but registered as "
            f"{expected_direction!r}"
        )

    # Expand wildcards first, then let concrete keys override, so a specific declaration
    # (e.g. "simulation.extra": full) beats a broad one (e.g. "simulation.*": none).
    expanded: dict[str, FieldCapability] = {}
    wildcard_keys = [k for k in caps.fields if k.endswith(".*")]
    concrete_keys = [k for k in caps.fields if not k.endswith(".*")]
    try:
        for key in wildcard_keys:
            for leaf in expand_capability_path(key):
                expanded[leaf] = caps.fields[key]
        for key in concrete_keys:
            (leaf,) = expand_capability_path(key)  # validates; a concrete path returns itself
            expanded[leaf] = caps.fields[key]
    except ValueError as exc:
        raise InvalidCapabilityDeclaration(f"{caps.format_id!r}: {exc}") from exc

    for path in caps.required_fields:
        if not is_valid_path(path):
            raise InvalidCapabilityDeclaration(
                f"{caps.format_id!r}: required_fields contains unknown canonical path {path!r}"
            )

    return caps.model_copy(update={"fields": expanded})


class CapabilityMatrix:
    """Queryable view over the registered capability declarations (§4.3). Keyed by
    ``(format_id, direction)``; a path not declared for a format reads as ``NONE`` —
    "the format cannot express it" is the safe default (§4.3)."""

    def __init__(self, declarations: dict[tuple[str, str], FormatCapabilities]) -> None:
        self._declarations = declarations

    def get(self, format_id: str, direction: str) -> FormatCapabilities:
        try:
            return self._declarations[(format_id, direction)]
        except KeyError:
            raise KeyError(
                f"no {direction!r} capabilities registered for format {format_id!r}"
            ) from None

    def field_capability(self, format_id: str, direction: str, path: str) -> FieldCapability:
        """Capability of ``format_id`` (in ``direction``) for one canonical path. An
        undeclared path defaults to ``NONE`` (§4.3)."""
        caps = self.get(format_id, direction)
        return caps.fields.get(path, FieldCapability(level=CapabilityLevel.NONE))


class Registry:
    """Explicit-list registry of parsers, exporters, and analysis plugins (§4.1, §7.1)."""

    def __init__(self) -> None:
        self._parsers: dict[str, ParserPlugin] = {}
        self._exporters: dict[str, ExporterPlugin] = {}
        self._analysis: dict[str, AnalysisPlugin] = {}
        self._declarations: dict[tuple[str, str], FormatCapabilities] = {}

    def register_parser(self, parser: ParserPlugin) -> None:
        # A parser may register with no paired exporter (a read-only/parser-only format,
        # D159): the matrix row is read-side only, and such a format is never a conversion
        # target because targets are derived from ``exporters()``. The duplicate guard
        # below is per-direction, so a format may register both sides independently.
        if parser.format_id in self._parsers:
            raise ValueError(f"a parser is already registered for format {parser.format_id!r}")
        caps = _validate_and_expand(
            parser.capabilities(), expected_direction="read", expected_format_id=parser.format_id
        )
        self._parsers[parser.format_id] = parser
        self._declarations[(parser.format_id, "read")] = caps

    def register_exporter(self, exporter: ExporterPlugin) -> None:
        if exporter.format_id in self._exporters:
            raise ValueError(f"an exporter is already registered for format {exporter.format_id!r}")
        caps = _validate_and_expand(
            exporter.capabilities(),
            expected_direction="write",
            expected_format_id=exporter.format_id,
        )
        self._exporters[exporter.format_id] = exporter
        self._declarations[(exporter.format_id, "write")] = caps

    def register_analysis_plugin(self, plugin: AnalysisPlugin) -> None:
        """Register an analysis plugin under its ``name`` namespace (v1.8 M68; Part 2 §6, §7.1).

        An analysis plugin carries no capability declaration: it reads a Canonical Object and
        annotates its own ``user_metadata`` namespace, so it contributes no Capability Matrix row
        and is neither a conversion source nor a target. Registration is therefore the duplicate
        guard plus the name bookkeeping — and, by construction, nothing here can change what
        ``parsers()``/``exporters()`` report, so a rogue analysis plugin cannot widen the format
        surface (P6). The duplicate guard is on ``name``, the plugin's namespace: two plugins
        writing the same namespace is the one collision that would make an annotation
        unattributable.
        """
        if plugin.name in self._analysis:
            raise ValueError(f"an analysis plugin is already registered for name {plugin.name!r}")
        self._analysis[plugin.name] = plugin

    def parsers(self) -> list[ParserPlugin]:
        return list(self._parsers.values())

    def exporters(self) -> list[ExporterPlugin]:
        return list(self._exporters.values())

    def analysis_plugins(self) -> list[AnalysisPlugin]:
        return list(self._analysis.values())

    def get_parser(self, format_id: str) -> ParserPlugin:
        return self._parsers[format_id]

    def get_exporter(self, format_id: str) -> ExporterPlugin:
        return self._exporters[format_id]

    def capability_matrix(self) -> CapabilityMatrix:
        """Assemble the current registrations into a queryable matrix (§4.1)."""
        return CapabilityMatrix(dict(self._declarations))
