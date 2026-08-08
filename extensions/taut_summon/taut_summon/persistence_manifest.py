"""Lightweight Taut persistence manifest for Summon."""

from taut.persistence import PersistenceComponentSpec

summon = PersistenceComponentSpec(
    component_api_version=1,
    name="taut-summon",
    write_version=1,
    load_versions=frozenset({1}),
    schema_keys=frozenset({"summon_schema_version"}),
    implementation="taut_summon.persistence:create_component",
)

__all__ = ["summon"]
