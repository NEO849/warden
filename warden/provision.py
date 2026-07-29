"""
Structured-property auto-provisioning — makes Warden reproducible against ANY DataHub instance,
not just the one where the warden.* structured properties happen to already be registered (this
VPS's long-lived dev GMS).

warden/agent.py::WardenAgent.setup() already defines every warden.* structured property by calling
straight into the OWNING modules (warden/memory.py::define_properties, warden/reflection.py::
define_reflection_property) — that remains the single source of truth for WHAT gets defined and
is untouched here. What was missing for a fresh GMS is a single, idempotent entrypoint that (a)
checks whether a definition already exists before emitting, so a repeat run is a no-op report
instead of a silent re-emit, and (b) can be driven from the CLI (`warden provision`) without
needing a seeded demo graph first.

Does NOT touch the `warden-needs-review` GlobalTag (not a structured property; warden/agent.py's
own _define_needs_review_tag() already covers it by direct idempotent emit) and does NOT run any
part of the live chain demo — definition-writes only.
"""
from datahub.api.entities.structuredproperties.structuredproperties import StructuredProperties
from datahub.metadata.schema_classes import StructuredPropertyDefinitionClass

from warden.memory import PROPS as _MEMORY_PROPS

# urn:li:structuredProperty:warden.reflection — defined by reflection.py::define_reflection_property
# with its own (narrower) entity_types; mirrored here rather than imported as a constant because
# reflection.py only exposes the *function*, not the type/entity_types tuple this module needs to
# reconstruct the same definition for the existence-check/create loop below.
_REFLECTION_QN = "warden.reflection"

# entity_types accepted per warden.* property. warden/memory.py::define_properties() applies
# ["dataset", "mlModel", "mlFeature"] uniformly to every belief/governance field; warden.reflection
# is written only onto mlModel/dataset (see reflection.py::define_reflection_property). Mirrored
# here so provision() is the single source of truth for the FULL warden.* surface, not just the
# belief fields memory.py owns by itself.
_DEFAULT_ENTITY_TYPES = ["dataset", "mlModel", "mlFeature"]
_ENTITY_TYPES_OVERRIDE = {
    _REFLECTION_QN: ["mlModel", "dataset"],
}


def _all_property_specs() -> dict:
    """qualified_name -> DataHub structured-property type, merging warden/memory.py's belief/
    governance PROPS with warden/reflection.py's warden.reflection. This is the full warden.*
    surface a fresh GMS needs defined before WardenAgent can persist anything."""
    specs = dict(_MEMORY_PROPS)
    specs.setdefault(_REFLECTION_QN, "string")
    return specs


def _urn(qualified_name: str) -> str:
    return f"urn:li:structuredProperty:{qualified_name}"


def _definition_exists(graph, urn: str) -> bool:
    """True iff `urn` (a structuredProperty entity urn) already has a StructuredPropertyDefinition
    aspect on GMS. Uses get_aspect directly (same call memory.py/reader.py already make for every
    other aspect read) rather than graph.exists() — get_aspect returns None for "not defined yet"
    and only raises on a genuine transport/auth failure, so provision() fails loudly if GMS is
    truly unreachable instead of silently treating "can't tell" as "doesn't exist" and spamming
    duplicate emits."""
    return graph.get_aspect(urn, StructuredPropertyDefinitionClass) is not None


def provision(graph, force: bool = False) -> dict:
    """Idempotently ensure every warden.* structured property DEFINITION exists on `graph`'s GMS.

    For each qualified name from _all_property_specs(): check whether GMS already has a
    StructuredPropertyDefinition for it; if not (or force=True), emit one via the same
    StructuredProperties(...).generate_mcps() builder warden/memory.py and warden/reflection.py
    already use individually. Already-defined properties are left untouched — running this twice
    against the same GMS is a no-op the second time (skip, not overwrite/duplicate), which is what
    makes `warden provision` safe to put at the top of `make demo` on every run.

    Returns {"created": [...], "skipped": [...], "qualified_names": [...]} (all sorted) for the
    CLI to report back.
    """
    specs = _all_property_specs()
    created, skipped = [], []
    for qn, typ in sorted(specs.items()):
        urn = _urn(qn)
        if not force and _definition_exists(graph, urn):
            skipped.append(qn)
            continue
        entity_types = _ENTITY_TYPES_OVERRIDE.get(qn, _DEFAULT_ENTITY_TYPES)
        sp = StructuredProperties(id=qn, qualified_name=qn, display_name=qn, type=typ,
                                 cardinality="SINGLE", entity_types=entity_types)
        for mcp in sp.generate_mcps():
            graph.emit(mcp)
        created.append(qn)
    return {"created": created, "skipped": skipped, "qualified_names": sorted(specs)}
