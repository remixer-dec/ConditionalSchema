"""Schema transformation helpers used by ConditionalModel and CRecord."""

import copy
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Type

from pydantic import BaseModel

from conditions import AnyOf, NoneOf

_SCHEMA_CACHE_LIMIT = 8


def _strip_descriptions(schema: Any, _preserve_keys: bool = False) -> Any:
    """Remove schema annotations while reusing containers without descriptions."""
    if isinstance(schema, dict):
        result = None
        for key, value in schema.items():
            if key == "description" and not _preserve_keys:
                if result is None:
                    result = dict(schema)
                result.pop(key, None)
                continue

            preserve_child_keys = key in {"properties", "patternProperties", "$defs", "definitions"}
            updated_value = _strip_descriptions(value, preserve_child_keys)
            if updated_value is not value:
                if result is None:
                    result = dict(schema)
                result[key] = updated_value
        return schema if result is None else result

    if isinstance(schema, list):
        result = None
        for index, item in enumerate(schema):
            updated_item = _strip_descriptions(item)
            if updated_item is not item:
                if result is None:
                    result = list(schema)
                result[index] = updated_item
        return schema if result is None else result

    return schema


def _schema_fingerprint(value: Any) -> Tuple[Any, ...]:
    """Create a deterministic structural fingerprint for a JSON Schema value."""
    if isinstance(value, dict):
        return ("dict", tuple((key, _schema_fingerprint(item)) for key, item in sorted(value.items())))
    if isinstance(value, list):
        return ("list", tuple(_schema_fingerprint(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_schema_fingerprint(item) for item in value))
    try:
        hash(value)
    except TypeError:
        return (type(value).__qualname__, repr(value))
    return (type(value).__qualname__, value)


def _common_schema_properties(variant_schemas: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Find common properties using fingerprints, then verify matching values."""
    first_props = variant_schemas[0].get("properties", {})
    candidates = {key: (value, _schema_fingerprint(value)) for key, value in first_props.items()}

    for schema in variant_schemas[1:]:
        properties = schema.get("properties", {})
        for key, (candidate, fingerprint) in list(candidates.items()):
            if key not in properties:
                del candidates[key]
                continue
            value = properties[key]
            if _schema_fingerprint(value) != fingerprint or value != candidate:
                del candidates[key]
    return {key: value for key, (value, _) in candidates.items()}


def _replace_schema_refs(schema: Any, ref_names: Dict[str, str]) -> Any:
    """Rewrite local definition references while preserving the schema shape."""
    if isinstance(schema, dict):
        result = {}
        for key, value in schema.items():
            if key == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
                local_name = value.rsplit("/", 1)[-1]
                result[key] = f"#/$defs/{ref_names.get(local_name, local_name)}"
            else:
                result[key] = _replace_schema_refs(value, ref_names)
        return result
    if isinstance(schema, list):
        return [_replace_schema_refs(item, ref_names) for item in schema]
    return schema


def _merge_variant_schema_definitions(
    schema: Dict[str, Any], merged_defs: Dict[str, Any], variant_index: int
) -> Dict[str, Any]:
    """Merge one variant's definitions and namespace unequal collisions."""
    local_defs = schema.pop("$defs", {})
    if not local_defs:
        return schema

    def contains_local_ref(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                (key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"))
                or contains_local_ref(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_local_ref(item) for item in value)
        return False

    ref_names: Dict[str, str] = {}
    assigned_names: Set[str] = set()
    for local_name, definition in local_defs.items():
        global_name = local_name
        if global_name in merged_defs:
            if merged_defs[global_name] == definition and not contains_local_ref(definition):
                ref_names[local_name] = global_name
                continue
            global_name = f"{local_name}_{variant_index + 1}"
            while global_name in merged_defs or global_name in assigned_names or global_name in local_defs:
                global_name += "_"
        elif global_name in assigned_names:
            global_name = f"{local_name}_{variant_index + 1}"
            while global_name in merged_defs or global_name in assigned_names or global_name in local_defs:
                global_name += "_"
        ref_names[local_name] = global_name
        assigned_names.add(global_name)

    for local_name, definition in local_defs.items():
        global_name = ref_names[local_name]
        if global_name not in merged_defs:
            merged_defs[global_name] = _replace_schema_refs(definition, ref_names)
    return _replace_schema_refs(schema, ref_names)


def _build_compact_schema(variant_schemas: List[Dict[str, Any]], merged_defs: Dict[str, Any]) -> Dict[str, Any]:
    """Extract properties shared by every variant into one definition."""
    common_props = _common_schema_properties(variant_schemas)
    if not common_props:
        result: Dict[str, Any] = {"anyOf": variant_schemas}
        if merged_defs:
            result["$defs"] = merged_defs
        return result

    all_required = [set(schema.get("required", [])) for schema in variant_schemas]
    base_required = set.intersection(*all_required) & set(common_props)
    base_def: Dict[str, Any] = {"type": "object", "properties": common_props}
    if base_required:
        base_def["required"] = sorted(base_required)

    compact_variants = []
    for schema in variant_schemas:
        variant_props = {key: value for key, value in schema.get("properties", {}).items() if key not in common_props}
        variant_required = [required for required in schema.get("required", []) if required not in base_required]
        variant_extra: Dict[str, Any] = {}
        if variant_props:
            variant_extra["properties"] = variant_props
        if variant_required:
            variant_extra["required"] = variant_required
        if variant_extra:
            compact_variants.append({"allOf": [{"$ref": "#/$defs/Base"}, variant_extra], "unevaluatedProperties": False})
        else:
            compact_variants.append({"$ref": "#/$defs/Base", "unevaluatedProperties": False})

    base_name = "__conditional_base__"
    while base_name in merged_defs:
        base_name += "_"
    compact_variants = [_replace_schema_refs(variant, {"Base": base_name}) for variant in compact_variants]
    return {"anyOf": compact_variants, "$defs": {base_name: base_def, **merged_defs}}


def _schema_property_name(model: Type[BaseModel], field_name: str, by_alias: bool) -> str:
    if not by_alias:
        return field_name
    field_info = model.model_fields.get(field_name)
    return field_info.alias if field_info and field_info.alias else field_name


def _condition_value_schema(value: Any) -> Dict[str, Any]:
    if isinstance(value, AnyOf):
        return {"enum": list(value.get_values())}
    if isinstance(value, NoneOf):
        return {"not": {"enum": list(value.get_values())}}
    return {"const": value}


def _condition_set_schema(model: Type[BaseModel], conditions: Dict[str, Any], by_alias: bool) -> Dict[str, Any]:
    properties = {
        _schema_property_name(model, field_name, by_alias): _condition_value_schema(value)
        for field_name, value in conditions.items()
    }
    result: Dict[str, Any] = {"properties": properties}
    if conditions:
        result["required"] = [_schema_property_name(model, field_name, by_alias) for field_name in conditions]
    return result


def _conditional_schema_predicate(model: Type[BaseModel], cond_info: Any, by_alias: bool) -> Optional[Dict[str, Any]]:
    predicates: List[Dict[str, Any]] = []
    if cond_info.when:
        predicates.append(_condition_set_schema(model, cond_info.when, by_alias))
    if cond_info.when_any:
        predicates.append(
            {"anyOf": [_condition_set_schema(model, condition_set, by_alias) for condition_set in cond_info.when_any]}
        )
    if not predicates:
        return None
    return predicates[0] if len(predicates) == 1 else {"allOf": predicates}


def _build_conditional_schema(model: Type[BaseModel], by_alias: bool = False) -> Dict[str, Any]:
    """Build one schema with conditional rules instead of a branch cross-product."""
    schema = BaseModel.model_json_schema.__func__(model, by_alias=by_alias)
    conditional_fields = getattr(model, "__cfields__", {})
    required = list(schema.get("required", []))
    for field_name, cond_info in conditional_fields.items():
        property_name = _schema_property_name(model, field_name, by_alias)
        predicate = _conditional_schema_predicate(model, cond_info, by_alias)
        if predicate is None:
            if cond_info.default is ... and property_name not in required:
                required.append(property_name)
            continue
        schema.setdefault("allOf", []).append(
            {
                "if": predicate,
                "then": {"required": [property_name]} if cond_info.default is ... else {},
                "else": {"not": {"required": [property_name]}},
            }
        )
        schema.get("properties", {}).get(property_name, {}).pop("default", None)
    if required:
        schema["required"] = required
    elif "required" in schema:
        schema.pop("required")
    return schema


def _cache_schema_result(model: Type[BaseModel], cache_key: Tuple[bool, bool, bool], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Store a private canonical copy and return a separate caller-owned copy."""
    schema_cache = model.__dict__.get("__schema_cache__")
    if schema_cache is None:
        schema_cache = {}
        type.__setattr__(model, "__schema_cache__", schema_cache)
    elif cache_key not in schema_cache and len(schema_cache) >= _SCHEMA_CACHE_LIMIT:
        schema_cache.pop(next(iter(schema_cache)))
    schema_cache[cache_key] = copy.deepcopy(schema)
    return copy.deepcopy(schema_cache[cache_key])


__all__ = [
    "_build_compact_schema",
    "_build_conditional_schema",
    "_cache_schema_result",
    "_common_schema_properties",
    "_condition_set_schema",
    "_condition_value_schema",
    "_conditional_schema_predicate",
    "_merge_variant_schema_definitions",
    "_replace_schema_refs",
    "_schema_fingerprint",
    "_schema_property_name",
    "_strip_descriptions",
]
