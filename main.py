"""
Conditional Pydantic Schema Library with Dynamic Templates
"""

from __future__ import annotations

import itertools
from typing import (
  Any,
  Callable,
  Dict,
  FrozenSet,
  List,
  Literal,
  Optional,
  Sequence,
  Set,
  Tuple,
  Type,
  Union,
  get_args,
  get_origin,
  overload,
)

from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo

CYesNo = Literal["yes", "no"]


class AnyOf:
  """Represents a condition that matches if the value is any of the given options."""

  __slots__ = ("_values", "_frozen_values")

  def __init__(self, *values: Any):
    self._values = tuple(values)  # Use tuple for immutability
    # Pre-compute frozen set for O(1) lookups
    self._frozen_values: FrozenSet[Any] = frozenset(values)

  def evaluate(self, actual: Any) -> bool:
    return actual in self._frozen_values

  def get_values(self) -> Tuple[Any, ...]:
    return self._values

  def __repr__(self) -> str:
    return f"AnyOf({', '.join(repr(v) for v in self._values)})"


class NoneOf:
  """Represents a condition that matches if the value is NONE of the given options."""

  __slots__ = ("_values", "_frozen_values")

  def __init__(self, *values: Any):
    self._values = tuple(values)
    self._frozen_values: FrozenSet[Any] = frozenset(values)

  def evaluate(self, actual: Any) -> bool:
    return actual not in self._frozen_values

  def get_values(self) -> Tuple[Any, ...]:
    return self._values

  def __repr__(self) -> str:
    return f"NoneOf({', '.join(repr(v) for v in self._values)})"


def any_of(*values: Any) -> AnyOf:
  """Create a condition that matches if the value is any of the given options."""
  return AnyOf(*values)


def none_of(*values: Any) -> NoneOf:
  """Create a condition that matches if the value is none of the given options."""
  return NoneOf(*values)


def truthy(val: Any) -> bool:
  """Check if a value is truthy."""
  return bool(val)


class Template:
  """Represents a template value that can be resolved with context."""

  __slots__ = ("value",)

  def __init__(self, value: Union[str, Callable[[Dict], Any]]):
    self.value = value

  def resolve(self, ctx: Dict[str, Any]) -> Any:
    if callable(self.value):
      return self.value(ctx)
    elif isinstance(self.value, str) and "{" in self.value:
      return self.value.format(**ctx)
    return self.value

  def __repr__(self) -> str:
    return f"Template({self.value!r})"


def Ctemplate(value: Union[str, Callable[[Dict], Any]]) -> Template:
  """Create a template for dynamic value resolution."""
  return Template(value)


class LiteralTemplate:
  """
  Template for creating state-dependent Literal types.

  Supports two modes:
  1. Mapping mode: Maps bind-time context values to different Literal options
  2. Conditional mode: Uses a lambda to select between two option lists

  Examples:
      # Mapping mode
      action: str = CField(
          Cliteral("mode", {
              "create": ["save", "cancel"],
              "edit": ["save", "delete", "cancel"],
          }),
          when_bound=["mode"]
      )

      # Conditional mode with lambda
      location_type: str = CField(
          Cliteral("location", lambda loc: len(loc) > 10,
                   if_true=["Long location"],
                   if_false=["Short location"]),
          when_truthy=["location"]
      )
  """

  __slots__ = ("key", "mapping", "default", "condition", "if_true", "if_false")

  def __init__(
    self,
    key: str,
    mapping_or_condition: Union[Dict[Any, List[Any]], Callable[[Any], bool]],
    default_or_if_true: Optional[List[Any]] = None,
    if_false: Optional[List[Any]] = None,
  ):
    self.key = key

    if callable(mapping_or_condition) and not isinstance(mapping_or_condition, dict):
      # Conditional mode: lambda, if_true, if_false
      self.mapping = None
      self.default = None
      self.condition = mapping_or_condition
      self.if_true = default_or_if_true
      self.if_false = if_false
    else:
      # Mapping mode: dict, default
      self.mapping = mapping_or_condition
      self.default = default_or_if_true
      self.condition = None
      self.if_true = None
      self.if_false = None

  def resolve(self, ctx: Dict[str, Any]) -> Type:
    """Resolve to a Literal type based on context."""
    value = ctx.get(self.key)

    if self.condition is not None:
      # Conditional mode
      if self.condition(value):
        options = self.if_true
      else:
        options = self.if_false

      if options is None:
        raise ValueError(f"Cliteral condition returned {self.condition(value)}, but corresponding options list is None")
    else:
      # Mapping mode
      options = self.mapping.get(value, self.default)

      if options is None:
        raise ValueError(
          f"No Literal options defined for {self.key}={value!r} "
          f"and no default provided. Available keys: {list(self.mapping.keys())}"
        )

    if not options:
      raise ValueError(f"Empty options list for {self.key}={value!r}")

    # Resolve any template placeholders in the literal values
    resolved_options = []
    for opt in options:
      if isinstance(opt, str) and "{" in opt:
        resolved_options.append(opt.format(**ctx))
      else:
        resolved_options.append(opt)

    return Literal[tuple(resolved_options)]

  def __repr__(self) -> str:
    if self.condition is not None:
      return f"Cliteral({self.key!r}, <condition>, if_true={self.if_true!r}, if_false={self.if_false!r})"
    return f"Cliteral({self.key!r}, {self.mapping!r})"


@overload
def Cliteral(key: str, mapping: Dict[Any, List[Any]], default: Optional[List[Any]] = None) -> LiteralTemplate: ...


@overload
def Cliteral(
  key: str,
  condition: Callable[[Any], bool],
  if_true: List[Any],
  if_false: List[Any],
) -> LiteralTemplate: ...


def Cliteral(
  key: str,
  mapping_or_condition: Union[Dict[Any, List[Any]], Callable[[Any], bool]],
  default_or_if_true: Optional[List[Any]] = None,
  if_false: Optional[List[Any]] = None,
  *,
  if_true: Optional[List[Any]] = None,
) -> LiteralTemplate:
  """
  Create a state-dependent Literal type.

  Two modes:

  1. Mapping mode - map context values to literal options:
      Cliteral(key, {value1: [options], value2: [options]}, default=[options])

  2. Conditional mode - use lambda to choose between two option lists:
      Cliteral(key, lambda val: condition, if_true=[options], if_false=[options])

  Literal values can contain {placeholder} templates that are resolved at bind time.

  Examples:
      # Mapping mode
      action: str = CField(
          Cliteral("mode", {
              "create": ["save", "cancel"],
              "edit": ["save", "delete", "cancel"],
          }),
          when_truthy=["mode"]
      )

      # Conditional mode
      location_desc: str = CField(
          Cliteral("location",
                   lambda loc: len(loc) > 10,
                   if_true=["Long location"],
                   if_false=["Short location"]),
          when_truthy=["location"]
      )

      # With template placeholders in literal values
      guide: str = CField(
          Cliteral("mode", {
              "chat": ["I will answer in {language} as {char_name}."],
              "formal": ["Responding formally in {language}."],
          }),
          when_truthy=["mode"]
      )
      # bind(mode="chat", language="English", char_name="Claude")
      # -> Literal["I will answer in English as Claude."]
  """
  # When if_true is passed as keyword, use it instead of default_or_if_true for conditional mode
  actual_if_true = if_true if if_true is not None else default_or_if_true
  return LiteralTemplate(key, mapping_or_condition, actual_if_true, if_false)


class CRecord:
  """
  Creates a dynamic object schema from runtime data where property names come from the data itself.

  This is useful when you have a list or dict of items and want to create a schema where:
  - Each property name is derived from a field in the data
  - Each property uses a specific model's schema

  Supports two modes for data input:
  1. List of dicts: Property names extracted from each item
  2. Dict of dicts: Keys used as property names (values are the items)

  Supports three modes for key extraction:
  1. Field name: Uses the field name to look up values in items
  2. Alias: Uses the model field's alias to look up values (use_alias=True)
  3. Callable: Custom function to extract key from each item

  Example:
      # Given data like:
      old_armor = [
          {"armor_item_name": "helmet", "defense": 10},
          {"armor_item_name": "chestplate", "defense": 25},
      ]

      # Create a record schema
      armor_record = CRecord(
          data=old_armor,
          key_field="armor_item_name",
          item_schema=UpdatableArmorItemModel,
      )

      # Get the schema
      schema = armor_record.json_schema()
      # {
      #   "type": "object",
      #   "properties": {
      #     "helmet": {...UpdatableArmorItemModel schema...},
      #     "chestplate": {...UpdatableArmorItemModel schema...},
      #   },
      #   "required": ["helmet", "chestplate"]
      # }

      # Access original data mapping
      data_map = armor_record.data_map
      # {"helmet": {"armor_item_name": "helmet", "defense": 10}, ...}
  """

  __slots__ = (
    "_data",
    "_key_field",
    "_item_schema",
    "_use_alias",
    "_required",
    "_flatten",
    "_data_map",
    "_model",
    "_additional_properties",
  )

  def __init__(
    self,
    data: Union[List[Dict[str, Any]], Dict[str, Dict[str, Any]]],
    key_field: Union[str, Callable[[Dict[str, Any]], str]],
    item_schema: Type[BaseModel],
    use_alias: bool = False,
    required: bool = True,
    flatten: bool = False,
    additional_properties: bool = False,
  ):
    """
    Create a dynamic record schema.

    Args:
        data: Input data - either a list of dicts or a dict of dicts.
              For list: property names are extracted using key_field.
              For dict: the dict keys become property names.
        key_field: How to extract property names from data items.
              - str: Field name to use (looks up item[key_field])
              - Callable: Function that takes an item and returns the key
        item_schema: Pydantic model that defines the schema for each property's value.
        use_alias: If True and key_field is a string, uses the model field's alias
                   to look up values in items. Defaults to False.
        required: If True, all properties are required. Defaults to True.
        additional_properties: If True, allows additional properties in the schema.
    """
    self._data = data
    self._key_field = key_field
    self._item_schema = item_schema
    self._use_alias = use_alias
    self._required = required
    self._additional_properties = additional_properties
    self._data_map: Optional[Dict[str, Dict[str, Any]]] = None
    self._model: Optional[Type[BaseModel]] = None
    self._flatten = flatten

  def _get_lookup_key(self) -> str:
    """Get the key to use for looking up values in data items."""
    if callable(self._key_field):
      return None  # Callable handles its own extraction

    if not self._use_alias:
      return self._key_field

    # Get alias from model field
    field_info = self._item_schema.model_fields.get(self._key_field)
    if field_info and field_info.alias:
      return field_info.alias
    return self._key_field

  def _extract_key(self, item: Dict[str, Any]) -> str:
    """Extract the property key from a data item."""
    if callable(self._key_field):
      return self._key_field(item)

    lookup_key = self._get_lookup_key()
    return item.get(lookup_key)

  def _build_data_map(self) -> Dict[str, Dict[str, Any]]:
    """Build the mapping from property names to original data items."""
    if self._data_map is not None:
      return self._data_map

    if isinstance(self._data, dict):
      # Dict input: keys are property names, values are items
      self._data_map = dict(self._data)
    else:
      # List input: extract keys from each item
      self._data_map = {}
      for item in self._data:
        key = self._extract_key(item)
        if key is not None:
          self._data_map[key] = item

    return self._data_map

  @property
  def data_map(self) -> Dict[str, Dict[str, Any]]:
    """
    Get the mapping from property names to original data items.

    Returns:
        Dict mapping property names to their corresponding original data items.
    """
    return self._build_data_map()

  @property
  def keys(self) -> List[str]:
    """Get the list of property names."""
    return list(self.data_map.keys())

  def model(self) -> Type[BaseModel]:
    """
    Get a dynamically created Pydantic model representing this record.

    Returns:
        A Pydantic model class with properties from the data.
    """
    if self._model is not None:
      return self._model

    data_map = self._build_data_map()

    # Create fields for the dynamic model
    fields: Dict[str, Tuple[Type, Any]] = {}
    fields_info = list(self._item_schema.model_fields.items())
    single_field = self._flatten and len(fields_info) == 1
    value_type = fields_info[0][1].annotation if single_field else self._item_schema

    for key in data_map.keys():
      if self._required:
        fields[key] = (value_type, ...)
      else:
        fields[key] = (Optional[value_type], None)

    self._model = create_model("DynamicRecord", **fields)
    if single_field:
      type.__setattr__(self._model, "__crecord_item_schema__", self._item_schema)
    return self._model

  def json_schema(self, by_alias: bool = False) -> Dict[str, Any]:
    """
    Get the JSON schema for this dynamic record.

    Args:
        by_alias: If True, uses aliases in the item schema.

    Returns:
        JSON schema dict with properties from the data.
    """
    data_map = self._build_data_map()
    fields_info = list(self._item_schema.model_fields.items())
    if self._flatten and len(fields_info) == 1:
      single_field_name = fields_info[0][0]
      full_schema = self._item_schema.model_json_schema(by_alias=by_alias)
      item_schema = full_schema.get("properties", {}).get(single_field_name, {})
    else:
      item_schema = self._item_schema.model_json_schema(by_alias=by_alias)

    schema = {
      "type": "object",
      "properties": {key: item_schema for key in data_map.keys()},
    }

    if self._required:
      schema["required"] = list(data_map.keys())

    if not self._additional_properties:
      schema["additionalProperties"] = False

    return schema

  def __repr__(self) -> str:
    return f"CRecord(keys={self.keys!r}, item_schema={self._item_schema.__name__})"


class CRecordTemplate:
  """
  Template for creating dynamic record schemas at bind time.

  Similar to CRecord but designed for use with ConditionalModel.bind().
  The data is retrieved from the bind context rather than being passed directly.

  Example:
      class UpdateForm(ConditionalModel):
          armor: dict = CField(
              Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
              when_truthy=["armor_data"]
          )

      BoundForm = UpdateForm.bind(armor_data=old_armor)
      schema = BoundForm.json_schema()
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
    key_field: Union[str, Callable[[Dict[str, Any]], str]],
    item_schema: Type[BaseModel],
    use_alias: bool = False,
    required: bool = True,
    flatten: bool = False,
    additional_properties: bool = False,
  ):
    """
    Create a record template for bind-time resolution.

    Args:
        data_key: Context key to retrieve data from during binding.
        key_field: How to extract property names from data items.
        item_schema: Pydantic model for each property's schema.
        use_alias: If True, uses aliases for key lookup.
        required: If True, all properties are required.
        additional_properties: If True, allows additional properties.
    """
    self._data_key = data_key
    self._key_field = key_field
    self._item_schema = item_schema
    self._use_alias = use_alias
    self._required = required
    self._additional_properties = additional_properties
    self._flatten = flatten
    self._resolved_record: Optional[CRecord] = None

  @property
  def data_key(self) -> str:
    """The context key used to retrieve data."""
    return self._data_key

  def resolve(self, ctx: Dict[str, Any]) -> Type[BaseModel]:
    """
    Resolve to a dynamically generated model at bind time.

    Args:
        ctx: Bind context containing the data.

    Returns:
        Dynamically created Pydantic model, or dict if data not found.
        When data is not found, returns dict type as placeholder (field
        will likely be excluded by when_truthy conditions anyway).
    """
    data = ctx.get(self._data_key)

    if data is None:
      # Return dict as placeholder - field will be excluded by when_truthy
      return dict

    self._resolved_record = CRecord(
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
  def resolved_record(self) -> Optional[CRecord]:
    """Get the resolved CRecord after binding (None if not yet resolved)."""
    return self._resolved_record

  def __repr__(self) -> str:
    return f"Crecord({self._data_key!r}, {self._key_field!r}, {self._item_schema.__name__})"


def Crecord(
  data_key: str,
  key_field: Union[str, Callable[[Dict[str, Any]], str]],
  item_schema: Type[BaseModel],
  use_alias: bool = False,
  required: bool = True,
  flatten: bool = False,
  additional_properties: bool = False,
) -> CRecordTemplate:
  """
  Create a dynamic record template for bind-time schema generation.

  This creates an object schema where property names come from runtime data.
  Use this with ConditionalModel when you need to create schemas based on
  external data that's only available at bind time.

  Args:
      data_key: Context key to retrieve data from during binding.
      key_field: How to extract property names from data items.
          - str: Field name to look up in each item
          - Callable: Function(item) -> str that extracts the key
      item_schema: Pydantic model defining each property's schema.
      use_alias: If True and key_field is a string, uses the model field's
                 alias to look up values in items. Defaults to False.
      required: If True, all generated properties are required. Defaults to True.
      additional_properties: If True, allows additional properties. Defaults to False.

  Returns:
      CRecordTemplate that resolves at bind time.

  Example:
      class ArmorItemModel(BaseModel):
          armor_item_name: str = Field(alias="armorItemName")
          defense: int

      class UpdatableArmorItemModel(BaseModel):
          defense: int = Field(ge=0, le=100)

      class UpdateArmorForm(ConditionalModel):
          armor_updates: dict = CField(
              Crecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
              when_truthy=["armor_data"]
          )

      # At bind time, data is provided
      old_armor = [
          {"armor_item_name": "helmet", "defense": 10},
          {"armor_item_name": "chestplate", "defense": 25},
      ]
      BoundForm = UpdateArmorForm.bind(armor_data=old_armor)

      # Schema includes properties for each armor item
      schema = BoundForm.json_schema()
      # armor_updates will have properties: {"helmet": ..., "chestplate": ...}

      # Using aliases for key lookup
      armor_record = Crecord("armor_data", "armor_item_name",
                             UpdatableArmorItemModel, use_alias=True)
      # Now looks for "armorItemName" in data items instead of "armor_item_name"

      # Using callable for custom key extraction
      armor_record = Crecord("armor_data",
                             lambda item: item["name"].lower(),
                             UpdatableArmorItemModel)
  """
  return CRecordTemplate(
    data_key=data_key,
    key_field=key_field,
    item_schema=item_schema,
    use_alias=use_alias,
    required=required,
    flatten=flatten,
    additional_properties=additional_properties,
  )


class _TruthyCheck:
  """Sentinel class to indicate a truthy check condition."""

  __slots__ = ()

  def __call__(self, val: Any) -> bool:
    return bool(val)

  def __repr__(self) -> str:
    return "TRUTHY"


class _FalsyCheck:
  """Sentinel class to indicate a falsy check condition."""

  __slots__ = ()

  def __call__(self, val: Any) -> bool:
    return not bool(val)

  def __repr__(self) -> str:
    return "FALSY"


class _UnboundCheck:
  """Sentinel to check if a key is NOT present in context."""

  __slots__ = ("_marker",)

  def __init__(self):
    self._marker = object()

  def check(self, ctx: Dict[str, Any], key: str) -> bool:
    return ctx.get(key, self._marker) is self._marker

  def __repr__(self) -> str:
    return "UNBOUND"


TRUTHY = _TruthyCheck()
FALSY = _FalsyCheck()
UNBOUND = _UnboundCheck()


class ConditionalFieldInfo:
  """
  Holds information about a conditional field.

  Attributes:
      field_type: The type of the field (can be LiteralTemplate for dynamic Literals)
      when: Dict mapping field names to required values for this field to be active
      when_any: List of condition dicts - field is active if ANY condition matches
      when_bound: Conditions checked at bind time (dict or list for truthy checks)
      when_truthy: List of context keys that must be truthy for field to be active
      when_falsy: List of context keys that must be falsy for field to be active
      when_unbound: List of context keys that must NOT be present for field to be active
      default: Default value when field is active
      alias: Field alias for JSON serialization
      description: Field description
      pattern: Regex pattern for validation
      enum: Enum values for validation
  """

  __slots__ = (
    "field_type",
    "when",
    "when_any",
    "when_bound",
    "when_truthy",
    "when_falsy",
    "when_unbound",
    "default",
    "alias",
    "description",
    "pattern",
    "enum",
    "field_kwargs",
    "bound_active_result",
    "_dependency_fields_cache",
  )

  def __init__(
    self,
    field_type: Union[Type, LiteralTemplate] = None,
    when: Optional[Dict[str, Any]] = None,
    when_any: Optional[List[Dict[str, Any]]] = None,
    when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
    when_truthy: Optional[List[str]] = None,
    when_falsy: Optional[List[str]] = None,
    when_unbound: Optional[List[str]] = None,
    default: Any = ...,
    alias: Optional[str] = None,
    description: Optional[Union[str, Template]] = None,
    pattern: Optional[Union[str, Template]] = None,
    enum: Optional[Union[List, Template]] = None,
    **field_kwargs: Any,
  ):
    self.field_type = field_type
    self.when = when or {}
    self.when_any = when_any
    self.default = default
    self.alias = alias
    self.description = description
    self.pattern = pattern
    self.enum = enum
    self.field_kwargs = field_kwargs
    self.bound_active_result = True
    self._dependency_fields_cache: Optional[FrozenSet[str]] = None

    # Initialize condition lists
    self.when_truthy: List[str] = list(when_truthy) if when_truthy else []
    self.when_falsy: List[str] = list(when_falsy) if when_falsy else []
    self.when_unbound: List[str] = list(when_unbound) if when_unbound else []

    # Process when_bound - support both dict and list formats
    self.when_bound: Dict[str, Any] = {}

    if when_bound is not None:
      if isinstance(when_bound, (list, tuple)):
        # List format: treat each item as a truthy check
        self.when_truthy.extend(when_bound)
      elif isinstance(when_bound, dict):
        self.when_bound = dict(when_bound)
      else:
        raise TypeError(f"when_bound must be a dict or list, got {type(when_bound).__name__}")

  @property
  def dependency_fields(self) -> FrozenSet[str]:
    """Get the set of field names this field depends on (for runtime conditions)."""
    if self._dependency_fields_cache is None:
      deps: Set[str] = set(self.when.keys())
      if self.when_any:
        for cond_set in self.when_any:
          deps.update(cond_set.keys())
      self._dependency_fields_cache = frozenset(deps)
    return self._dependency_fields_cache

  def evaluate(self, combo: Dict[str, Any]) -> bool:
    """Evaluate if the field should be active for a given combination of control values."""
    # Check 'when' conditions (all must match)
    for field_name, condition in self.when.items():
      if field_name not in combo:
        return False
      actual = combo[field_name]
      if isinstance(condition, AnyOf):
        if not condition.evaluate(actual):
          return False
      elif isinstance(condition, NoneOf):
        if not condition.evaluate(actual):
          return False
      elif actual != condition:
        return False

    # Check 'when_any' conditions (at least one set must match)
    if self.when_any:
      any_matched = False
      for condition_set in self.when_any:
        all_in_set_match = True
        for field_name, condition in condition_set.items():
          if field_name not in combo:
            all_in_set_match = False
            break
          actual = combo[field_name]
          if isinstance(condition, AnyOf):
            if not condition.evaluate(actual):
              all_in_set_match = False
              break
          elif isinstance(condition, NoneOf):
            if not condition.evaluate(actual):
              all_in_set_match = False
              break
          elif actual != condition:
            all_in_set_match = False
            break
        if all_in_set_match:
          any_matched = True
          break
      if not any_matched:
        return False

    return True

  def evaluate_bound(self, ctx: Dict[str, Any]) -> bool:
    """Evaluate bind-time conditions."""
    # Check unbound conditions (keys must NOT be in context)
    _marker = object()
    for key in self.when_unbound:
      if ctx.get(key, _marker) is not _marker:
        return False

    # Check truthy conditions
    for key in self.when_truthy:
      if not bool(ctx.get(key)):
        return False

    # Check falsy conditions
    for key in self.when_falsy:
      if bool(ctx.get(key)):
        return False

    # Check dict-based conditions
    for key, condition in self.when_bound.items():
      actual = ctx.get(key)
      if isinstance(condition, AnyOf):
        if not condition.evaluate(actual):
          return False
      elif isinstance(condition, NoneOf):
        if not condition.evaluate(actual):
          return False
      elif callable(condition):
        if not condition(actual):
          return False
      elif actual != condition:
        return False

    return True

  @property
  def requires_bind(self) -> bool:
    """Check if this field requires bind() to be called."""
    return bool(
      self.when_truthy
      or self.when_falsy
      or self.when_unbound
      or self.when_bound
      or isinstance(self.field_type, LiteralTemplate)
      or isinstance(self.field_type, CRecordTemplate)
      or isinstance(self.pattern, Template)
      or isinstance(self.enum, Template)
      or (isinstance(self.description, str) and "{" in self.description)
      or (isinstance(self.alias, str) and "{" in self.alias)
      or isinstance(self.description, Template)
      or (get_origin(self.field_type) is Literal and any(isinstance(a, str) and "{" in a for a in get_args(self.field_type)))
    )

  def resolve_aliases(self, alias_to_field: Dict[str, str]) -> None:
    """Resolve alias keys in when/when_any conditions to field names."""
    if not alias_to_field:
      return

    changed = False

    # Resolve aliases in 'when' conditions
    if self.when:
      resolved_when = {}
      for key, value in self.when.items():
        resolved_key = alias_to_field.get(key)
        if resolved_key:
          resolved_when[resolved_key] = value
          changed = True
        else:
          resolved_when[key] = value
      if changed:
        self.when = resolved_when

    # Resolve aliases in 'when_any' conditions
    if self.when_any:
      resolved_when_any = []
      any_changed = False
      for cond_set in self.when_any:
        resolved_set = {}
        set_changed = False
        for key, value in cond_set.items():
          resolved_key = alias_to_field.get(key)
          if resolved_key:
            resolved_set[resolved_key] = value
            set_changed = True
          else:
            resolved_set[key] = value
        resolved_when_any.append(resolved_set if set_changed else cond_set)
        if set_changed:
          any_changed = True
      if any_changed:
        self.when_any = resolved_when_any
        changed = True

    # Clear dependency cache only if conditions changed
    if changed:
      self._dependency_fields_cache = None

  def resolve_templates(self, ctx: Dict[str, Any]) -> "ConditionalFieldInfo":
    """Resolve all template values with the given context."""

    def resolve(val: Any) -> Any:
      if isinstance(val, Template):
        return val.resolve(ctx)
      elif isinstance(val, str) and "{" in val:
        return val.format(**ctx)
      return val

    # Resolve field type
    resolved_type = self.field_type

    if isinstance(self.field_type, LiteralTemplate):
      # Resolve LiteralTemplate to actual Literal type
      resolved_type = self.field_type.resolve(ctx)
    elif isinstance(self.field_type, CRecordTemplate):
      # Resolve CRecordTemplate to a dynamically generated model
      resolved_type = self.field_type.resolve(ctx)
    elif get_origin(self.field_type) is Literal:
      # Resolve string templates in Literal args
      args = get_args(self.field_type)
      new_args = []
      for arg in args:
        if isinstance(arg, str) and "{" in arg:
          new_args.append(arg.format(**ctx))
        else:
          new_args.append(arg)
      resolved_type = Literal[tuple(new_args)]

    bound_active = self.evaluate_bound(ctx)

    result = ConditionalFieldInfo(
      field_type=resolved_type,
      when=self.when,
      when_any=self.when_any,
      when_bound={},  # Already evaluated
      when_truthy=[],  # Already evaluated
      when_falsy=[],  # Already evaluated
      when_unbound=[],  # Already evaluated
      default=self.default,
      alias=resolve(self.alias),
      description=resolve(self.description),
      pattern=resolve(self.pattern),
      enum=resolve(self.enum),
      **self.field_kwargs,
    )
    result.bound_active_result = bound_active
    return result

  def make_field_info(self) -> Tuple[Type, FieldInfo]:
    """Create Pydantic field info for an active field."""
    extra = dict(self.field_kwargs)

    if self.pattern:
      extra["pattern"] = self.pattern
    if self.enum:
      extra["json_schema_extra"] = {"enum": self.enum}

    return (
      self.field_type,
      Field(
        default=self.default,
        alias=self.alias,
        description=self.description,
        **extra,
      ),
    )


@overload
def CField(
  field_type: Union[Type, LiteralTemplate],
  *,
  when: Optional[Dict[str, Any]] = None,
  when_any: Optional[List[Dict[str, Any]]] = None,
  when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
  when_truthy: Optional[List[str]] = None,
  when_falsy: Optional[List[str]] = None,
  when_unbound: Optional[List[str]] = None,
  default: Any = ...,
  alias: Optional[str] = None,
  description: Optional[Union[str, Template]] = None,
  pattern: Optional[Union[str, Template]] = None,
  enum: Optional[Union[List, Template]] = None,
  **field_kwargs: Any,
) -> Any: ...


@overload
def CField(
  *,
  when: Optional[Dict[str, Any]] = None,
  when_any: Optional[List[Dict[str, Any]]] = None,
  when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
  when_truthy: Optional[List[str]] = None,
  when_falsy: Optional[List[str]] = None,
  when_unbound: Optional[List[str]] = None,
  default: Any = ...,
  alias: Optional[str] = None,
  description: Optional[Union[str, Template]] = None,
  pattern: Optional[Union[str, Template]] = None,
  enum: Optional[Union[List, Template]] = None,
  **field_kwargs: Any,
) -> Any: ...


def CField(
  field_type: Union[Type, LiteralTemplate] = None,
  *,
  when: Optional[Dict[str, Any]] = None,
  when_any: Optional[List[Dict[str, Any]]] = None,
  when_bound: Optional[Union[Dict[str, Any], List[str]]] = None,
  when_truthy: Optional[List[str]] = None,
  when_falsy: Optional[List[str]] = None,
  when_unbound: Optional[List[str]] = None,
  default: Any = ...,
  alias: Optional[str] = None,
  description: Optional[Union[str, Template]] = None,
  pattern: Optional[Union[str, Template]] = None,
  enum: Optional[Union[List, Template]] = None,
  **field_kwargs: Any,
) -> Any:
  """
  Create a conditional field.

  Args:
      field_type: The type of the field. Can be:
          - Regular type (str, int, etc.)
          - Literal["a", "b"]
          - Cliteral("key", {...}) for state-dependent Literals
          - None or ... to infer from annotation
      when: Dict of runtime field conditions (all must match).
            Keys are Python field NAMES (not aliases).
      when_any: List of condition dicts - field active if ANY matches.
                Keys are Python field NAMES (not aliases).
      when_bound: Bind-time conditions. Can be:
          - Dict[str, Any]: {key: condition} where condition is value, callable, or AnyOf
          - List[str]: List of context keys that must be truthy
      when_truthy: List of context keys that must be truthy
      when_falsy: List of context keys that must be falsy
      when_unbound: List of context keys that must NOT be in bind context
      default: Default value
      alias: JSON alias for serialization. When json_schema(by_alias=True) is called,
             this alias will be used in the schema instead of the field name.
             Conditions (when, when_any) always use field NAMES, not aliases.
      description: Field description (can be Template)
      pattern: Regex pattern (can be Template)
      enum: Enum values (can be Template)
      **field_kwargs: Additional Pydantic Field kwargs

  Returns:
      ConditionalFieldInfo instance

  Examples:
      # Simple condition - uses field NAME 'enabled', not alias
      name: str = CField(when={"enabled": True})

      # With alias - condition uses 'has_pet' (name), schema can use 'hasPet' (alias)
      class Form(ConditionalModel):
          has_pet: CYesNo = CField(alias="hasPet")
          pet_name: str = CField(
              alias="petName",
              when={"has_pet": "yes"}  # Uses field NAME, not alias
          )

      # Default schema uses field names
      Form.json_schema()
      # {"properties": {"has_pet": ..., "pet_name": ...}}

      # by_alias=True uses aliases
      Form.json_schema(by_alias=True)
      # {"properties": {"hasPet": ..., "petName": ...}}

      # Template placeholders in Literal (type inferred from annotation)
      guide: Literal["I will answer in {language}."] = CField(
          when_truthy=["language"]
      )

      # Truthy bind-time check
      city: str = CField(when_bound=["location"])

      # Falsy bind-time check
      placeholder: str = CField(when_falsy=["has_value"])

      # Unbound check (field active when key is NOT in context)
      default_mode: str = CField(when_unbound=["mode"])

      # State-dependent Literal
      action: str = CField(
          Cliteral("mode", {
              "create": ["save", "cancel"],
              "edit": ["save", "delete", "cancel"],
          }),
          when_truthy=["mode"]
      )
  """
  # Treat Ellipsis as None (infer from annotation)
  if field_type is ...:
    field_type = None

  return ConditionalFieldInfo(
    field_type=field_type,
    when=when,
    when_any=when_any,
    when_bound=when_bound,
    when_truthy=when_truthy,
    when_falsy=when_falsy,
    when_unbound=when_unbound,
    default=default,
    alias=alias,
    description=description,
    pattern=pattern,
    enum=enum,
    **field_kwargs,
  )


def _has_template_in_type(field_type: Any) -> bool:
  """Check if a type annotation contains template placeholders."""
  if isinstance(field_type, LiteralTemplate):
    return True
  if get_origin(field_type) is Literal:
    return any(isinstance(a, str) and "{" in a for a in get_args(field_type))
  return False


def _strip_descriptions(schema: Any) -> Any:
  """Recursively remove all 'description' keys from a schema dict."""
  if isinstance(schema, dict):
    return {k: _strip_descriptions(v) for k, v in schema.items() if k != "description"}
  if isinstance(schema, list):
    return [_strip_descriptions(item) for item in schema]
  return schema


def _build_compact_schema(variant_schemas: List[Dict[str, Any]], merged_defs: Dict[str, Any]) -> Dict[str, Any]:
  """
  Build a compact anyOf schema by extracting common properties into $defs/Base.

  Fields with identical schemas across all variants are extracted to a shared
  base definition, so each variant only lists its unique (discriminator/conditional)
  fields.
  """
  # Find properties whose schema is identical in every variant
  first_props = variant_schemas[0].get("properties", {})
  common_props = {
    key: val
    for key, val in first_props.items()
    if all(s.get("properties", {}).get(key) == val for s in variant_schemas[1:])
  }

  if not common_props:
    # Nothing to share; fall back to standard anyOf
    result: Dict[str, Any] = {"anyOf": variant_schemas}
    if merged_defs:
      result["$defs"] = merged_defs
    return result

  all_required = [set(s.get("required", [])) for s in variant_schemas]
  # Base required = fields required in every variant AND defined in Base properties
  base_required = set.intersection(*all_required) & set(common_props.keys())

  base_def: Dict[str, Any] = {"type": "object", "properties": common_props}
  if base_required:
    base_def["required"] = sorted(base_required)

  compact_variants = []
  for schema in variant_schemas:
    variant_props = {k: v for k, v in schema.get("properties", {}).items() if k not in common_props}
    variant_required = [r for r in schema.get("required", []) if r not in base_required]

    variant_extra: Dict[str, Any] = {}
    if variant_props:
      variant_extra["properties"] = variant_props
    if variant_required:
      variant_extra["required"] = variant_required

    if variant_extra:
      compact_variants.append({"allOf": [{"$ref": "#/$defs/Base"}, variant_extra]})
    else:
      compact_variants.append({"$ref": "#/$defs/Base"})

  defs = {"Base": base_def, **merged_defs}
  return {"anyOf": compact_variants, "$defs": defs}


def _get_control_values(
  control_fields: FrozenSet[str],
  annotations: Dict[str, Type],
  conditional_fields: Dict[str, ConditionalFieldInfo],
) -> Dict[str, Tuple[Any, ...]]:
  """
  Determine possible values for each control field.
  Uses tuples for memory efficiency and hashability.
  """
  control_values: Dict[str, Tuple[Any, ...]] = {}

  for cf_name in control_fields:
    if cf_name in annotations:
      ann = annotations[cf_name]
      origin = get_origin(ann)
      if origin is Literal:
        control_values[cf_name] = get_args(ann)
      elif ann is bool:
        control_values[cf_name] = (True, False)
      else:
        # Collect possible values from conditions
        possible: Set[Any] = set()
        for cond_info in conditional_fields.values():
          if cf_name in cond_info.when:
            c = cond_info.when[cf_name]
            if isinstance(c, AnyOf):
              possible.update(c.get_values())
            elif isinstance(c, NoneOf):
              # For NoneOf, we need all values except these
              pass  # Can't determine without full domain
            else:
              possible.add(c)
        control_values[cf_name] = tuple(possible) if possible else (True, False)

  return control_values


def _generate_combos(
  control_fields: Sequence[str],
  control_values: Dict[str, Tuple[Any, ...]],
) -> List[Dict[str, Any]]:
  """Generate all combinations of control field values using itertools.product."""
  if not control_fields:
    return [{}]

  value_lists = [control_values.get(f, (None,)) for f in control_fields]
  combos = []

  for values in itertools.product(*value_lists):
    combo = dict(zip(control_fields, values))
    combos.append(combo)

  return combos


class ConditionalModelMeta(type(BaseModel)):
  """Metaclass for ConditionalModel that handles variant generation."""

  def __new__(mcs, name: str, bases: Tuple[type, ...], namespace: Dict[str, Any], **kwargs):
    # Skip processing for base class and bound classes
    if name == "ConditionalModel" or name.endswith("_Bound"):
      return super().__new__(mcs, name, bases, namespace, **kwargs)

    # Remove private attributes that Pydantic adds
    from pydantic.fields import ModelPrivateAttr

    for key in list(namespace.keys()):
      if isinstance(namespace[key], ModelPrivateAttr):
        del namespace[key]

    conditional_fields: Dict[str, ConditionalFieldInfo] = {}
    regular_fields: Dict[str, Tuple[Type, Any]] = {}
    annotations = namespace.get("__annotations__", {})

    # Separate conditional fields from regular fields
    for field_name, field_value in list(namespace.items()):
      if isinstance(field_value, ConditionalFieldInfo):
        if field_value.field_type is None:
          field_value.field_type = annotations.get(field_name, Any)
        conditional_fields[field_name] = field_value

        # FIX: Only convert to Pydantic field if it doesn't require binding
        # Fields with templates or bind-time conditions must wait for .bind()
        if not field_value.requires_bind:
          ftype, finfo = field_value.make_field_info()
          namespace[field_name] = finfo
        else:
          # Keep it as ConditionalFieldInfo for now, will be resolved at bind time
          # Create a placeholder field so the base model at least knows about it
          extra = dict(field_value.field_kwargs)
          # Don't include template values that haven't been resolved
          if not isinstance(field_value.pattern, Template):
            extra["pattern"] = field_value.pattern
          if not isinstance(field_value.enum, Template):
            if field_value.enum:
              extra["json_schema_extra"] = {"enum": field_value.enum}

          namespace[field_name] = Field(
            default=field_value.default,
            alias=field_value.alias,
            description=field_value.description if not isinstance(field_value.description, Template) else None,
            **extra,
          )

      elif field_name in annotations and not field_name.startswith("_"):
        if isinstance(field_value, FieldInfo):
          regular_fields[field_name] = (annotations[field_name], field_value)
        elif field_value is not ...:
          regular_fields[field_name] = (annotations[field_name], field_value)
        else:
          regular_fields[field_name] = (annotations[field_name], ...)

    # Build alias-to-field-name mapping for resolving aliases in when conditions
    alias_to_field: Dict[str, str] = {}
    for field_name, (_, field_value) in regular_fields.items():
      if isinstance(field_value, FieldInfo) and field_value.alias:
        alias_to_field[field_value.alias] = field_name
    for field_name, cond_info in conditional_fields.items():
      if cond_info.alias:
        alias_to_field[cond_info.alias] = field_name

    # Resolve aliases in when conditions to field names
    for cond_info in conditional_fields.values():
      cond_info.resolve_aliases(alias_to_field)

    # Check if binding is required
    needs_bind = any(cf.requires_bind for cf in conditional_fields.values())

    # Generate variants now if no binding is needed
    if not needs_bind:
      variants = mcs._generate_variants(name, regular_fields, conditional_fields, annotations)
    else:
      variants = []

    # Create the class
    cls = super().__new__(mcs, name, bases, namespace, **kwargs)

    # Attach metadata
    type.__setattr__(cls, "__cfields__", conditional_fields)
    type.__setattr__(cls, "__rfields__", regular_fields)
    type.__setattr__(cls, "__annots__", annotations)
    type.__setattr__(cls, "__needs_bind__", needs_bind)
    type.__setattr__(cls, "__variants__", variants)

    return cls

  @staticmethod
  def _generate_variants(
    name: str,
    regular_fields: Dict[str, Tuple[Type, Any]],
    conditional_fields: Dict[str, ConditionalFieldInfo],
    annotations: Dict[str, Type],
  ) -> List[Type[BaseModel]]:
    """Generate all variant models based on control field combinations."""

    # Collect all control fields (fields that affect conditional logic)
    # Exclude control fields that are inactive conditional fields
    control_fields: Set[str] = set()
    for cf in conditional_fields.values():
      for dep_field in cf.dependency_fields:
        # Skip if the dependency is an inactive conditional field
        if dep_field in conditional_fields:
          if not conditional_fields[dep_field].bound_active_result:
            continue
        control_fields.add(dep_field)

    control_fields_frozen = frozenset(control_fields)

    # Get possible values for each control field
    control_values = _get_control_values(control_fields_frozen, annotations, conditional_fields)

    # Generate all combinations
    combos = _generate_combos(list(control_fields), control_values)

    variants = []
    seen_signatures: Set[FrozenSet[str]] = set()

    for combo in combos:
      variant_fields: Dict[str, Tuple[Type, Any]] = {}
      active_conditional_fields: Set[str] = set()

      # Iteratively resolve active conditional fields
      changed = True
      while changed:
        changed = False
        for field_name, cond_info in conditional_fields.items():
          if field_name in active_conditional_fields:
            continue

          if not cond_info.bound_active_result:
            continue

          temp_combo = {}
          for k, v in combo.items():
            if k in regular_fields or k in active_conditional_fields or k not in conditional_fields:
              temp_combo[k] = v

          if cond_info.evaluate(temp_combo):
            active_conditional_fields.add(field_name)
            changed = True

      # Evaluate each conditional field
      conditional_field_values: Dict[str, Tuple[Type, Any]] = {}
      for field_name in active_conditional_fields:
        cond_info = conditional_fields[field_name]
        ftype, finfo = cond_info.make_field_info()
        conditional_field_values[field_name] = (ftype, finfo)

      # Fix control field values in this variant
      control_field_overrides: Dict[str, Tuple[Type, Any]] = {}
      for cf_name, cf_val in combo.items():
        is_active_cf = cf_name in regular_fields or cf_name in active_conditional_fields or cf_name not in conditional_fields
        if not is_active_cf:
          continue

        if cf_name in annotations:
          # Preserve alias from regular field or conditional field
          alias = None
          if cf_name in regular_fields:
            _, original_field = regular_fields[cf_name]
            if isinstance(original_field, FieldInfo) and original_field.alias:
              alias = original_field.alias
          elif cf_name in conditional_fields:
            cond_field = conditional_fields[cf_name]
            if cond_field.alias:
              alias = cond_field.alias

          if alias:
            control_field_overrides[cf_name] = (
              Literal[cf_val],
              Field(alias=alias),
            )
          else:
            control_field_overrides[cf_name] = (Literal[cf_val], ...)

      # Build variant_fields in original annotation order
      for field_name in annotations.keys():
        if field_name in control_field_overrides:
          variant_fields[field_name] = control_field_overrides[field_name]
        elif field_name in conditional_field_values:
          variant_fields[field_name] = conditional_field_values[field_name]
        elif field_name in regular_fields:
          variant_fields[field_name] = regular_fields[field_name]

      # Create signature to deduplicate equivalent variants
      active_combo = {k: v for k, v in combo.items() if k in control_field_overrides}
      signature_parts = [f"{k}={v}" for k, v in sorted(active_combo.items())] + sorted(active_conditional_fields)
      signature = frozenset(signature_parts)

      # Skip duplicate variants
      if signature in seen_signatures:
        continue
      seen_signatures.add(signature)

      # Create variant name
      suffix_parts = [str(v) for v in active_combo.values()] if active_combo else ["default"]
      suffix = "_".join(suffix_parts)

      variant = create_model(f"{name}_{suffix}", **variant_fields)
      variants.append(variant)

    return variants


class ConditionalModel(BaseModel, metaclass=ConditionalModelMeta):
  """
  Base class for models with conditional fields.

  Conditional fields can be shown/hidden based on:
  - Runtime values of other fields (generates anyOf variants)
  - Bind-time context values (evaluated at .bind() call)

  Example:
      class MyForm(ConditionalModel):
          has_pet: CYesNo
          pet_name: str = CField(when={"has_pet": "yes"})

      # Get JSON schema with anyOf variants
      schema = MyForm.json_schema()

      # With bind-time conditions
      class LocationForm(ConditionalModel):
          city: str = CField(when_bound=["location"])  # truthy check

      BoundForm = LocationForm.bind(location="NYC")
      schema = BoundForm.json_schema()
  """

  class Config:
    populate_by_name = True

  @classmethod
  def bind(cls, **ctx: Any) -> Type["ConditionalModel"]:
    """
    Bind the model with context values.

    This resolves:
    - Template values in descriptions, patterns, enums
    - LiteralTemplate types (Cliteral)
    - when_bound conditions
    - when_truthy conditions
    - when_falsy conditions
    - when_unbound conditions

    Args:
        **ctx: Context values for templates and bind-time conditions

    Returns:
        A new ConditionalModel subclass with resolved variants

    Example:
        class Form(ConditionalModel):
            detail: str = CField(
                when_truthy=["show_detail"],
                description=Ctemplate("Details for {entity}")
            )
            action: str = CField(
                Cliteral("mode", {
                    "create": ["save", "cancel"],
                    "edit": ["save", "delete", "cancel"],
                }),
                when_truthy=["mode"]
            )

        BoundForm = Form.bind(show_detail=True, entity="User", mode="edit")
    """
    cfields = cls.__cfields__
    rfields = cls.__rfields__
    annots = cls.__annots__

    # Resolve templates and evaluate bound conditions
    resolved = {name: cf.resolve_templates(ctx) for name, cf in cfields.items()}

    # Generate variants with resolved fields
    variants = ConditionalModelMeta._generate_variants(
      cls.__name__,
      rfields,
      resolved,
      annots,
    )

    # Build namespace for the bound model so Pydantic populates model_fields
    namespace: Dict[str, Any] = {"__annotations__": {}}

    for name in annots:
      if name in rfields:
        typ, val = rfields[name]
        namespace["__annotations__"][name] = typ
        if val is not ...:
          namespace[name] = val
      elif name in resolved:
        cf = resolved[name]
        if cf.bound_active_result:
          ftype, finfo = cf.make_field_info()
          namespace["__annotations__"][name] = ftype
          namespace[name] = finfo

    # Create bound class
    new_cls = type(f"{cls.__name__}_Bound", (ConditionalModel,), namespace)
    type.__setattr__(new_cls, "__variants__", variants)
    type.__setattr__(new_cls, "__cfields__", resolved)
    type.__setattr__(new_cls, "__rfields__", rfields)
    type.__setattr__(new_cls, "__annots__", annots)
    type.__setattr__(new_cls, "__needs_bind__", False)
    type.__setattr__(new_cls, "__bind_ctx__", ctx)

    return new_cls

  @classmethod
  def _get_variants(cls) -> List[Type[BaseModel]]:
    """Get all generated variant models (internal use)."""
    return cls.__variants__

  @classmethod
  def _as_union(cls) -> Type:
    """Get the model as a Union type of all variants (internal use)."""
    variants = cls._get_variants()
    if len(variants) == 1:
      return variants[0]
    return Union[tuple(variants)]

  @classmethod
  def json_schema(cls, by_alias: bool = False, compact: bool = False, descriptions: bool = True) -> Dict[str, Any]:
    """
    Get the JSON schema for this model.

    If there are multiple variants, returns an anyOf schema.
    If there's one variant, returns that variant's schema directly.

    Args:
        by_alias: If True, use field aliases in schema instead of field names.
                 Falls back to field name if no alias is defined.
        compact: If True, extract fields common to all variants into a shared
                 $defs/Base reference to reduce schema size.
        descriptions: If False, strip all 'description' fields from the schema.

    Raises:
        ValueError: If the model has bind-time conditions and .bind()
                   hasn't been called.

    Example:
        class Form(ConditionalModel):
            user_name: str = CField(str, alias="userName")

        # Default - uses field names
        Form.json_schema()
        # {"properties": {"user_name": {...}}}

        # With by_alias - uses aliases
        Form.json_schema(by_alias=True)
        # {"properties": {"userName": {...}}}
    """
    if cls.__needs_bind__:
      raise ValueError(
        "Schema has bind-time conditions (when_bound, when_truthy, "
        "when_falsy, when_unbound, templates, or Cliteral). "
        "Call .bind() first to resolve them."
      )
    variants = cls._get_variants()
    if len(variants) == 1:
      schema = variants[0].model_json_schema(by_alias=by_alias)
      return schema if descriptions else _strip_descriptions(schema)

    # Collect schemas and merge $defs to root level
    variant_schemas = [v.model_json_schema(by_alias=by_alias) for v in variants]
    merged_defs = {}
    cleaned_schemas = []

    for schema in variant_schemas:
      if "$defs" in schema:
        merged_defs.update(schema["$defs"])
        schema_copy = {k: v for k, v in schema.items() if k != "$defs"}
        cleaned_schemas.append(schema_copy)
      else:
        cleaned_schemas.append(schema)

    if compact:
      result = _build_compact_schema(cleaned_schemas, merged_defs)
    else:
      result = {"anyOf": cleaned_schemas}
      if merged_defs:
        result["$defs"] = merged_defs

    return result if descriptions else _strip_descriptions(result)

  @staticmethod
  def _extract_nested_models(field_type: Any) -> "Set[Type[BaseModel]]":
    """Recursively extract BaseModel subclasses from a type annotation."""
    models: Set[Type[BaseModel]] = set()
    if field_type is None:
      return models
    if isinstance(field_type, CRecordTemplate):
      models.add(field_type._item_schema)
      return models
    if isinstance(field_type, type) and issubclass(field_type, BaseModel):
      if field_type.__name__ == "DynamicRecord":
        item_schema = getattr(field_type, "__crecord_item_schema__", None)
        if item_schema is not None:
          models.add(item_schema)
          return models
        for f in field_type.model_fields.values():
          ann = f.annotation
          if get_origin(ann) is Union:
            for arg in get_args(ann):
              if arg is not type(None) and isinstance(arg, type) and issubclass(arg, BaseModel):
                models.add(arg)
          elif ann is not None and isinstance(ann, type) and issubclass(ann, BaseModel):
            models.add(ann)
        return models
      models.add(field_type)
      return models
    origin = get_origin(field_type)
    if origin is not None:
      for arg in get_args(field_type):
        models.update(ConditionalModel._extract_nested_models(arg))
    return models

  @staticmethod
  def _nested_model_propdoc(model: Type[BaseModel], by_alias: bool = False, ctx: Dict[str, Any] = {}) -> str:
    lines = []
    for field_name, field_info in model.model_fields.items():
      prop_name = (field_info.alias or field_name) if by_alias else field_name
      line = f"  {prop_name}"
      desc = field_info.description
      if desc and isinstance(desc, str) and "{" in desc and ctx:
        desc = desc.format(**ctx)
      if desc:
        line += f": {desc}"
      field_type = model.__annotations__.get(field_name)
      if field_type is not None and get_origin(field_type) is Literal:
        opts = ", ".join(str(a) for a in get_args(field_type))
        line += f" (Choose one: {opts})"
      lines.append(line)
    return "\n".join(lines)

  @classmethod
  def propdoc(
    cls,
    by_alias: bool = False,
    lazy: bool = True,
    mention_depends: bool = False,
    mention_options: bool = False,
  ) -> str:
    """
    Get a compact documentation string for all properties.

    Args:
        by_alias: If True, use field aliases instead of field names.
        lazy: If True (default), ignore bind-time conditions and list all properties.
              If False, only include properties that pass bind-time conditions.
        mention_depends: If True, add condition text like "only if x is y" for each field.
                         This can be slower as it analyzes all conditions.
        mention_options: If True, show available options for Literal and enum fields.

    Returns:
        A multi-line string with property names and their descriptions.
    Example:
        class Form(ConditionalModel):
            name: str = CField(alias="userName", description="User's full name")
            age: int = CField(description="User's age", when={"has_age": True})

        print(Form.propdoc())
        # name: User's full name
        # age: User's age

        print(Form.propdoc(by_alias=True, mention_depends=True))
        # userName: User's full name
        # age: User's age (only if has_age is True)
    """
    cache_key = (by_alias, lazy, mention_depends, mention_options)
    cache = getattr(cls, "__propdoc_cache__", None)
    if cache is None:
      cache = {}
      type.__setattr__(cls, "__propdoc_cache__", cache)

    if cache_key in cache:
      return cache[cache_key]

    lines = []
    nested_models: Dict[Type[BaseModel], List[str]] = {}  # model -> list of field names using it
    nested_model_is_record: Set[Type[BaseModel]] = set()
    bind_ctx = getattr(cls, "__bind_ctx__", {})
    cfields = getattr(cls, "__cfields__", {})
    rfields = getattr(cls, "__rfields__", {})
    annots = getattr(cls, "__annots__", {})

    active_fields = set(annots.keys())
    if not getattr(cls, "__needs_bind__", False):
      active_fields = set()
      for variant in getattr(cls, "__variants__", []):
        active_fields.update(variant.model_fields.keys())

    for field_name in annots.keys():
      if field_name not in active_fields:
        continue

      prop_name = field_name
      description = None
      condition_text = ""
      options_text = ""
      field_type = annots.get(field_name)

      if field_name in cfields:
        cond_info = cfields[field_name]

        if by_alias and cond_info.alias:
          prop_name = cond_info.alias

        if isinstance(cond_info.description, Template):
          desc_val = cond_info.description.value
          if isinstance(desc_val, str):
            description = desc_val
          elif callable(desc_val):
            description = "<dynamic>"
          else:
            description = str(desc_val)
        else:
          desc = cond_info.description
          if isinstance(desc, Template):
            description = desc.resolve(bind_ctx)
          elif isinstance(desc, str) and "{" in desc and bind_ctx:
            description = desc.format(**bind_ctx)
          else:
            description = desc

        if mention_depends:
          alias_map = cls._build_alias_map() if by_alias else {}
          condition_text = cls._format_conditions(cond_info, alias_map)

        if mention_options:
          options_text = cls._get_options_text(cond_info.field_type, cond_info.enum)

        field_type = cond_info.field_type

      elif field_name in rfields:
        _, field_value = rfields[field_name]
        if isinstance(field_value, FieldInfo):
          if by_alias and field_value.alias:
            prop_name = field_value.alias
          description = field_value.description

        if mention_options:
          options_text = cls._get_options_text(field_type, None)

      else:
        if mention_options:
          options_text = cls._get_options_text(field_type, None)

      # Collect nested models
      for model in cls._extract_nested_models(field_type):
        nested_models.setdefault(model, []).append(prop_name)
        if isinstance(field_type, CRecordTemplate) or (
          isinstance(field_type, type) and issubclass(field_type, BaseModel) and field_type.__name__ == "DynamicRecord"
        ):
          nested_model_is_record.add(model)

      line = prop_name
      if description:
        line += f": {description}"
      if options_text:
        line += f" {options_text}"
      if condition_text:
        line += f" ({condition_text})"
      lines.append(line)

    # Append nested schema docs (each unique model only once)
    if nested_models:
      lines.append("")
      for model, used_by in nested_models.items():
        used_str = ", ".join(used_by)
        if model in nested_model_is_record:
          lines.append(f"{model.__name__} (record values, used by {used_str}):")
        else:
          lines.append(f"{model.__name__} (used by {used_str}):")
        inner = cls._nested_model_propdoc(model, by_alias=by_alias, ctx=bind_ctx)
        if inner:
          lines.append(inner)

    result = "\n".join(lines)
    cache[cache_key] = result
    return result

  @staticmethod
  def _get_options_text(field_type: Any, enum_values: Optional[List]) -> str:
    """Extract options text from Literal types or enum values."""
    options = []

    if enum_values:
      options = list(enum_values)
    elif field_type is not None:
      origin = get_origin(field_type)
      if origin is Literal:
        options = list(get_args(field_type))
      elif isinstance(field_type, LiteralTemplate):
        if field_type.mapping:
          all_opts = set()
          for opts in field_type.mapping.values():
            all_opts.update(opts)
          if field_type.default:
            all_opts.update(field_type.default)
          options = sorted(all_opts)
        elif field_type.if_true or field_type.if_false:
          all_opts = set()
          if field_type.if_true:
            all_opts.update(field_type.if_true)
          if field_type.if_false:
            all_opts.update(field_type.if_false)
          options = sorted(all_opts)

    if options:
      opts_str = ", ".join(str(o) for o in options)
      return f"(Choose one: {opts_str})"
    return ""

  @classmethod
  def _build_alias_map(cls) -> Dict[str, str]:
    """Build a mapping from field names to their aliases."""
    alias_map: Dict[str, str] = {}
    cfields = getattr(cls, "__cfields__", {})
    rfields = getattr(cls, "__rfields__", {})

    for field_name, cond_info in cfields.items():
      if cond_info.alias:
        alias_map[field_name] = cond_info.alias

    for field_name, (_, field_value) in rfields.items():
      if isinstance(field_value, FieldInfo) and field_value.alias:
        alias_map[field_name] = field_value.alias

    return alias_map

  @staticmethod
  def _format_conditions(
    cond_info: "ConditionalFieldInfo",
    alias_map: Optional[Dict[str, str]] = None,
  ) -> str:
    """Format condition information as a readable string."""
    parts = []

    def resolve_name(field: str) -> str:
      if alias_map:
        return alias_map.get(field, field)
      return field

    def format_condition(name: str, value: Any) -> str:
      if isinstance(value, AnyOf):
        vals = ", ".join(str(v) for v in value.get_values())
        return f"{name} is either {vals}"
      elif isinstance(value, NoneOf):
        vals = ", ".join(str(v) for v in value.get_values())
        return f"{name} is neither {vals}"
      else:
        return f"{name} is {value}"

    if cond_info.when:
      when_parts = [format_condition(resolve_name(f), v) for f, v in cond_info.when.items()]
      if when_parts:
        parts.append("only if " + " and ".join(when_parts))

    if cond_info.when_any:
      any_parts = []
      for cond_set in cond_info.when_any:
        set_parts = [format_condition(resolve_name(f), v) for f, v in cond_set.items()]
        if set_parts:
          any_parts.append("(" + " and ".join(set_parts) + ")")
      if any_parts:
        parts.append("when " + " or ".join(any_parts))

    if cond_info.when_truthy:
      resolved = [resolve_name(f) for f in cond_info.when_truthy]
      parts.append("requires " + ", ".join(resolved))

    if cond_info.when_falsy:
      resolved = [resolve_name(f) for f in cond_info.when_falsy]
      parts.append("requires not " + ", ".join(resolved))

    if cond_info.when_unbound:
      resolved = [resolve_name(f) for f in cond_info.when_unbound]
      parts.append("requires unset " + ", ".join(resolved))

    if cond_info.when_bound:
      bound_parts = []
      for field, value in cond_info.when_bound.items():
        name = resolve_name(field)
        if callable(value) and not isinstance(value, (AnyOf, NoneOf)):
          bound_parts.append(f"{name} matches condition")
        else:
          bound_parts.append(format_condition(name, value))
      if bound_parts:
        parts.append("bound " + " and ".join(bound_parts))

    return "; ".join(parts)


__all__ = [
  "CYesNo",
  "any_of",
  "none_of",
  "truthy",
  "TRUTHY",
  "FALSY",
  "UNBOUND",
  "Ctemplate",
  "Cliteral",
  "Crecord",
  "CField",
  "ConditionalModel",
  "Template",
  "LiteralTemplate",
  "CRecord",
  "CRecordTemplate",
  "AnyOf",
  "NoneOf",
  "ConditionalFieldInfo",
]
