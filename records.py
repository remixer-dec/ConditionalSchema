"""Runtime record schema helpers."""

import copy
from typing import Any, Callable, Dict, List, Optional, Type, Union, cast

from pydantic import BaseModel, ConfigDict, create_model


def _schema_property_name(model: Type[BaseModel], field_name: str, by_alias: bool) -> str:
    if not by_alias:
        return field_name
    field_info = model.model_fields.get(field_name)
    return field_info.alias if field_info and field_info.alias else field_name


class CSRecord:
    """Create a dynamic object schema whose property names come from runtime data."""

    __slots__ = (
        "_data",
        "_key_field",
        "_item_schema",
        "_use_alias",
        "_required",
        "_flatten",
        "_data_map",
        "_keys",
        "_model",
        "_additional_properties",
    )

    def __init__(
        self,
        data: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]],
        key_field: Union[str, Callable[[Dict[str, Any]], Any]],
        item_schema: Type[BaseModel],
        use_alias: bool = False,
        required: bool = True,
        flatten: bool = False,
        additional_properties: bool = False,
    ):
        """Validate and copy record input for a dynamic object schema.

        Args:
            data: A list of item mappings or a mapping from property names to items.
            key_field: Item field name or callable used to derive each property name.
            item_schema: Pydantic model used for each dynamic property value.
            use_alias: Look up ``key_field`` through the item model's alias.
            required: Require every data-derived property in the generated model.
            flatten: Use the sole item field's schema as the property value schema.
            additional_properties: Allow properties not present in ``data``.

        Raises:
            TypeError: If the input container, item, key field, or mapping key is invalid.
            ValueError: If a list item has a missing, duplicate, or non-string key.
        """
        if not isinstance(data, (list, dict)):
            raise TypeError("CSRecord data must be a list or dictionary")
        if not isinstance(key_field, str) and not callable(key_field):
            raise TypeError("CSRecord key_field must be a string or callable")
        if isinstance(data, dict):
            for key, item in data.items():
                if not isinstance(key, str):
                    raise TypeError("CSRecord dictionary keys must be strings")
                if not isinstance(item, dict):
                    raise TypeError("CSRecord dictionary values must be dictionaries")
        else:
            for item in data:
                if not isinstance(item, dict):
                    raise TypeError("CSRecord each item must be a dictionary")

        self._data = copy.deepcopy(data)
        self._key_field = key_field
        self._item_schema = item_schema
        self._use_alias = use_alias
        self._required = required
        self._flatten = flatten
        self._additional_properties = additional_properties
        self._data_map: Optional[Dict[str, Dict[str, Any]]] = None
        self._keys: Optional[tuple[str, ...]] = None
        self._model: Optional[Type[BaseModel]] = None

    def _get_lookup_key(self) -> Optional[str]:
        if callable(self._key_field):
            return None
        if not self._use_alias:
            return self._key_field
        field_info = self._item_schema.model_fields.get(self._key_field)
        if field_info and field_info.alias:
            return field_info.alias
        return self._key_field

    def _extract_key(self, item: Dict[str, Any]) -> Any:
        if callable(self._key_field):
            return self._key_field(item)
        lookup_key = self._get_lookup_key()
        return item.get(lookup_key) if lookup_key is not None else None

    def _build_data_map(self) -> Dict[str, Dict[str, Any]]:
        if self._data_map is not None:
            return self._data_map
        if isinstance(self._data, dict):
            self._data_map = dict(self._data)
        else:
            self._data_map = {}
            for index, item in enumerate(self._data):
                try:
                    key = self._extract_key(item)
                except Exception as exc:
                    raise ValueError(f"CSRecord could not extract a key from item {index}: {exc}") from exc
                if key is None:
                    raise ValueError(f"CSRecord item {index} is missing key {self._key_field!r}")
                if not isinstance(key, str):
                    raise ValueError(f"CSRecord key from item {index} must be a string, got {type(key).__name__}")
                if key in self._data_map:
                    raise ValueError(f"CSRecord has duplicate key {key!r}")
                self._data_map[key] = item
        return self._data_map

    @property
    def data_map(self) -> Dict[str, Dict[str, Any]]:
        """Return a defensive copy of the extracted input mapping."""
        return copy.deepcopy(self._build_data_map())

    @property
    def keys(self) -> List[str]:
        """Return record property names in declaration order."""
        if self._keys is None:
            self._keys = tuple(self._build_data_map())
        return list(self._keys)

    def model(self) -> Type[BaseModel]:
        """Return the cached dynamic Pydantic model for this record."""
        if self._model is not None:
            return self._model

        data_map = self._build_data_map()
        fields: Dict[str, tuple[Any, Any]] = {}
        fields_info = self._item_schema.model_fields
        single_field = self._flatten and len(fields_info) == 1
        single_field_info = next(iter(fields_info.values())) if single_field else None
        value_type = single_field_info.annotation if single_field_info is not None else self._item_schema

        for key in data_map:
            if self._required:
                field_value_type = value_type
                default = ...
            else:
                field_value_type = Optional[value_type] if single_field else value_type
                default = None

            if single_field_info is not None:
                field_info = copy.deepcopy(single_field_info)
                field_info.default = default
                field_info.alias = None
                field_info.validation_alias = None
                field_info.serialization_alias = None
                field_info.alias_priority = None
                fields[key] = (field_value_type, field_info)
            else:
                fields[key] = (field_value_type, default)

        config = ConfigDict(extra="allow" if self._additional_properties else "forbid")
        model = cast(Type[BaseModel], cast(Any, create_model)("DynamicRecord", __config__=config, **fields))
        type.__setattr__(model, "__conditional_dynamic_record__", True)
        type.__setattr__(model, "__crecord_item_schema__", self._item_schema)
        self._model = model
        return model

    def json_schema(self, by_alias: bool = False) -> Dict[str, Any]:
        """Return the dynamic schema with one root item definition.

        Args:
            by_alias: Use aliases from ``item_schema`` in the emitted item schema.

        Returns:
            A JSON-serializable object schema whose properties are derived from ``data``.
        """
        data_map = self._build_data_map()
        fields_info = self._item_schema.model_fields
        full_schema = self._item_schema.model_json_schema(by_alias=by_alias)
        if self._flatten and len(fields_info) == 1:
            field_name = next(iter(fields_info))
            property_name = _schema_property_name(self._item_schema, field_name, by_alias)
            item_schema = full_schema.get("properties", {}).get(property_name, {})
        else:
            item_schema = {key: value for key, value in full_schema.items() if key != "$defs"}

        definitions = copy.deepcopy(full_schema.get("$defs", {}))
        item_definition_name = "CSRecordItem"
        while item_definition_name in definitions:
            item_definition_name += "_"
        definitions[item_definition_name] = item_schema
        schema = {
            "type": "object",
            "properties": {key: {"$ref": f"#/$defs/{item_definition_name}"} for key in data_map},
            "$defs": definitions,
        }
        if self._required:
            schema["required"] = list(data_map)
        if not self._additional_properties:
            schema["additionalProperties"] = False
        return schema

    def __repr__(self) -> str:
        return f"CSRecord(keys={self.keys!r}, item_schema={self._item_schema.__name__})"


class CSRecordTemplate:
    """Resolve a :class:`CSRecord` from one bind-time context value.

    Args:
        data_key: Context key containing record data.
        key_field: Item field name or callable used to derive property names.
        item_schema: Pydantic model for each dynamic property value.
        use_alias: Use the item model alias for string key lookup.
        required: Require every data-derived property.
        flatten: Use the sole item field as the property value schema.
        additional_properties: Allow properties not present in the input.
    """

    __slots__ = (
        "_data_key",
        "_key_field",
        "_item_schema",
        "_use_alias",
        "_required",
        "_flatten",
        "_additional_properties",
        "_resolved_record",
    )

    def __init__(
        self,
        data_key: str,
        key_field: Union[str, Callable[[Dict[str, Any]], Any]],
        item_schema: Type[BaseModel],
        use_alias: bool = False,
        required: bool = True,
        flatten: bool = False,
        additional_properties: bool = False,
    ):
        self._data_key = data_key
        self._key_field = key_field
        self._item_schema = item_schema
        self._use_alias = use_alias
        self._required = required
        self._flatten = flatten
        self._additional_properties = additional_properties
        self._resolved_record: Optional[CSRecord] = None

    @property
    def data_key(self) -> str:
        return self._data_key

    @property
    def item_schema(self) -> Type[BaseModel]:
        return self._item_schema

    def resolve(self, ctx: Dict[str, Any]) -> Any:
        """Build the dynamic model from ``ctx[data_key]``.

        Missing data resolves to ``dict``. Invalid present data raises the same
        ``TypeError`` or ``ValueError`` as :class:`CSRecord` construction.
        """
        data = ctx.get(self._data_key)
        if data is None:
            return dict
        self._resolved_record = CSRecord(
            data=data,
            key_field=self._key_field,
            item_schema=self._item_schema,
            use_alias=self._use_alias,
            required=self._required,
            flatten=self._flatten,
            additional_properties=self._additional_properties,
        )
        return self._resolved_record.model()

    @property
    def resolved_record(self) -> Optional[CSRecord]:
        return self._resolved_record

    def __repr__(self) -> str:
        return f"CSrecord({self._data_key!r}, {self._key_field!r}, {self._item_schema.__name__})"


def CSrecord(
    data_key: str,
    key_field: Union[str, Callable[[Dict[str, Any]], Any]],
    item_schema: Type[BaseModel],
    use_alias: bool = False,
    required: bool = True,
    flatten: bool = False,
    additional_properties: bool = False,
) -> CSRecordTemplate:
    """Create a bind-time record template.

    ``key_field`` must be a string or callable; record data must contain mapping
    items and produce unique string property names when resolved.
    """
    return CSRecordTemplate(
        data_key,
        key_field,
        item_schema,
        use_alias=use_alias,
        required=required,
        flatten=flatten,
        additional_properties=additional_properties,
    )


__all__ = ["CSRecord", "CSRecordTemplate", "CSrecord"]
