## API Reference

### Supported Versions

This project requires Python 3.10+ and Pydantic v2 (`>=2,<3`). Install the `dev` extras to get tools for testing and linting (Ruff and Pyrefly).

Run the baseline checks with:

```bash
python -m pytest
ruff format --check .
ruff check .
pyrefly check
```

Install the development tools with `python -m pip install -e '.[dev]'`.

### Public Exports

Import these primary names from `main`: `CSYesNo`, `AnyOf`, `NoneOf`, `any_of`,
`none_of`, `truthy`, `TRUTHY`, `FALSY`, `UNBOUND`, `Template`,
`LiteralTemplate`, `CStemplate`, `CSliteral`, `CSRecord`, `CSRecordTemplate`,
`CSrecord`, `CSField`, `ConditionalFieldInfo`, and `ConditionalModel`. The
focused modules also re-export names for their subsystem.

### CSField Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `field_type` | `Type \| LiteralTemplate \| CSRecordTemplate \| None` | Field type. Omit it or use `...` to infer the type from the annotation. |
| `when` | `Dict[str, Any]` | Runtime conditions using field names. All conditions must match. |
| `when_any` | `List[Dict[str, Any]]` | OR conditions using field names. At least one condition must match. |
| `when_bound` | `Dict \| List` | For a dict, check conditions at bind time. For a list, require each context key to be truthy. |
| `when_truthy` | `List[str]` | Context keys that must be truthy |
| `when_falsy` | `List[str]` | Context keys that must be falsy |
| `when_unbound` | `List[str]` | Context keys that must NOT be present |
| `default` | `Any` | Default value |
| `alias` | `str` | JSON alias (used with `by_alias=True`) |
| `description` | `str \| Template` | Field description (may contain `{placeholder}` templates resolved at bind time) |
| `pattern` | `str \| Template` | Regex pattern |
| `enum` | `List \| Template` | Allowed values. Validation enforces them, and the schema includes them. |
| `**field_kwargs` | `Field` arguments | Additional Pydantic field metadata and constraints |

Use Python field names, not aliases, for runtime `when` and `when_any` keys.
The model rejects aliases that collide with another field name or alias when
the class is created.

### ConditionalModel Methods

| Method | Description |
|--------|-------------|
| `.bind(**ctx)` | Resolve templates and bind-time conditions |
| `._get_variants()` | Get list of variant models (internal use) |
| `._as_union()` | Get Union type of all variants (internal use) |
| `.model_validate(...)` / `.model_dump(...)` | Validate and serialize using the selected conditional variant |
| `.model_json_schema(...)` | Standard Pydantic schema method that includes conditional variants |
| `.json_schema(by_alias=False, compact=False, descriptions=True, cache=False)` | Return JSON Schema. Multiple variants use `anyOf`. The options control aliases, schema size, descriptions, and caching. |
| `.propdoc(by_alias=False, lazy=True, mention_depends=False, mention_options=False)` | Return compact property documentation, including nested model fields |

### Condition Helpers

| Helper | Description |
|--------|-------------|
| `any_of(*values)` | Match if value is ANY of the given options |
| `none_of(*values)` | Match if value is NONE of the given options |
| `AnyOf(*values)` | Condition object returned by `any_of` |
| `NoneOf(*values)` | Condition object returned by `none_of` |
| `truthy(value)` | Return `bool(value)` for a direct truthiness check |
| `CSliteral(key, mapping, default)` | State-dependent Literal type (mapping mode) |
| `CSliteral(key, condition, if_true=, if_false=)` | State-dependent Literal type (conditional mode) |
| `CStemplate(value)` | Template for dynamic strings/values |

`TRUTHY`, `FALSY`, and `UNBOUND` are special values for `when_bound` mappings.
`TRUTHY` and `FALSY` require the context key to exist and have the matching
boolean state. `UNBOUND` requires the key to be absent. A missing key is not
falsy and is not equal to `None`.

### Template Placeholders in Literals

Literal values can contain simple `{placeholder}` templates. They are resolved
at bind time:

```python
# Template in regular Literal (type inferred from annotation)
guide: Literal["I will answer in {language} as {char_name}."] = CSField(
    when_truthy=["language", "char_name"]
)
# bind(language="English", char_name="Claude")
# -> Literal["I will answer in English as Claude."]

# Template in CSliteral values
action: str = CSField(
    CSliteral("mode", {
        "chat": ["Reply as {char_name}"],
        "formal": ["Respond formally"],
    }),
    when_truthy=["mode"]
)
```

`CSField` descriptions, aliases, and enum entries containing `{` are resolved
at bind time without a wrapper. Patterns are literal by default, so regex
braces such as `{2,5}` work as written. Use `CStemplate(...)` for dynamic
patterns and callable templates.

RegExp patterns should exclude `"`, `]`, and `}`. The library warns when it
cannot find a negative character class with all three. For example:
`pattern=r'^Answer: [^"\]}]+$'`.
`ConditionalModel.bind(**context)` resolves these values before it generates
the bound schema. The bind context also resolves predicates. It does not
pre-fill or freeze runtime controller fields.

### JSON Schema Output Options

`ConditionalModel.json_schema()` accepts these output controls:

```python
# Extract properties shared by every variant into $defs/Base.
schema = BoundForm.json_schema(compact=True)

# Omit descriptions recursively for a smaller schema.
schema = BoundForm.json_schema(descriptions=False)

# Reuse the generated result when the same bound class is queried repeatedly.
schema = BoundForm.json_schema(cache=True)
```

Use `compact=True` for models with multiple variants. The compact form uses
`allOf` references to share common properties. The cache key includes
`by_alias`, `compact`, and `descriptions`.

When `cache=True`, each call returns a defensive copy, so mutating a returned
schema does not affect later calls or subclasses.

If a model has more finite controller combinations than the internal variant
limit, `json_schema()` emits `if`/`then`/`else` rules. It does not build a
Cartesian-product `anyOf`. `_as_union()` is capped for these models, so use
the JSON Schema output instead.

For each selected condition, generated variants reject inactive properties.
Runtime controller fields must use a finite `Literal`, `Enum`, or `bool`
annotation so the project can represent every branch. A conditional field's
finite `enum` metadata and a bound `CSliteral` also contribute to the
controller domains.

### CSliteral Modes

**Mapping mode** - map context values to literal options:
```python
action: str = CSField(
    CSliteral("mode", {
        "create": ["save", "cancel"],
        "edit": ["save", "delete", "cancel"],
    }, default=["ok"]),
    when_truthy=["mode"]
)
```

**Conditional mode** - use lambda to choose between two option lists:
```python
location_type: str = CSField(
    CSliteral("location",
             lambda loc: len(loc) > 10,
             if_true=["Long location"],
             if_false=["Short location"]),
    when_truthy=["location"]
)
```

### CSRecord - Dynamic Object Schemas from Data

CSRecord creates object schemas whose property names come from runtime data:

**Standalone usage with CSRecord:**
```python
from main import CSRecord

old_armor = [
    {"armor_item_name": "helmet", "defense": 10},
    {"armor_item_name": "chestplate", "defense": 25},
]

record = CSRecord(
    data=old_armor,
    key_field="armor_item_name",
    item_schema=UpdatableArmorItemModel,
)

# Get schema
schema = record.json_schema()
# {"type": "object", "properties": {"helmet": {...}, "chestplate": {...}}}

# Access original data
record.data_map  # {"helmet": {"armor_item_name": "helmet", ...}, ...}
record.keys      # ["helmet", "chestplate"]
```

**Bind-time usage with CSrecord:**
```python
class UpdateArmorForm(ConditionalModel):
    armor_updates: dict = CSField(
        CSrecord("armor_data", "armor_item_name", UpdatableArmorItemModel),
        when_truthy=["armor_data"]
    )

BoundForm = UpdateArmorForm.bind(armor_data=old_armor)
schema = BoundForm.json_schema()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `data` / `data_key` | `List[Dict] \| Dict[str, Dict]` / `str` | Data or context key |
| `key_field` | `str \| Callable` | Field name or function to extract property names |
| `item_schema` | `Type[BaseModel]` | Schema for each property's value |
| `use_alias` | `bool` | Use field alias for key lookup (default: False) |
| `required` | `bool` | Make all properties required (default: True) |
| `flatten` | `bool` | For a one-field item model, use that field's schema directly for each record value (default: False) |
| `additional_properties` | `bool` | Allow additional properties (default: False) |

**Flatten mode** - when `item_schema` has exactly one field, property values use that field's type directly instead of a nested object:

```python
class Score(BaseModel):
    value: int

record = CRecord(data=scores, key_field="name", item_schema=Score, flatten=True)
# {"type": "object", "properties": {"alice": {"type": "integer"}, ...}}
# Instead of: {"properties": {"alice": {"type": "object", "properties": {"value": ...}}}}
```

**Key extraction modes:**
```python
# Field name lookup
CSRecord(data, key_field="item_name", ...)

# Alias lookup (uses model field's alias)
CSRecord(data, key_field="item_name", use_alias=True, ...)

# Custom callable
CSRecord(data, key_field=lambda item: item["name"].lower(), ...)
```

**Flattening single-field item models:**

```python
class SettingValue(BaseModel):
    value: int

record = CSRecord(
    data=[{"name": "retries"}],
    key_field="name",
    item_schema=SettingValue,
    flatten=True,
)

# Each record property uses the integer schema directly rather than
# requiring {"value": ...}.
```

The same `flatten` option is available on `CSrecord(...)` for bind-time records.

Record input must contain dictionaries whose property keys are strings. Each
list record must provide a unique, non-missing string key. Malformed items and
missing or duplicate keys raise an error. Invalid callable results also raise
an error.
`CSRecord` copies input when it is created, and `data_map` returns a defensive
copy. Neither the source data nor the returned mapping can change the cached
model or schema. Each dynamic property references one canonical item
definition under the record schema's root `$defs`. Flattened fields preserve
aliases, constraints, and requiredness. The dynamic model uses the same
`additional_properties` policy as the standalone schema.

### Property Documentation

`propdoc()` produces a compact text list of the active properties. It can use
aliases and include condition descriptions. With `mention_options=True`, it
also shows Literal or enum options. Nested `BaseModel` fields appear once
below the parent properties. Dynamic record item models are labeled as record
values.

With the default `lazy=True`, the output includes every declared property,
including properties removed by a bound condition. With `lazy=False`, it
reports only properties in the generated variants. This requires a bound model
when bind-time conditions are used. Options keep their declaration order,
including heterogeneous Literal values.

```python
print(BoundForm.propdoc(by_alias=True, mention_depends=True, mention_options=True))
```

### Public Contracts and Errors

Use Python field names (not aliases) for runtime conditions. When the class is
created, the model raises `ValueError` for unknown or cyclic dependencies and
ambiguous aliases. Runtime controllers must use finite `Literal`, `Enum`, or
`bool` annotations. Other annotations raise `ValueError` before variants are
built. `when_bound` must be a mapping or list. Any other value raises
`TypeError`.

`CStemplate` formats strings with the supplied bind context. `bind()` passes
through missing formatting keys and exceptions from callable templates. Plain
`CSField` descriptions, aliases, and enum entries containing `{` are also
formatted by `bind()`. Patterns remain literal unless wrapped in
`CStemplate(...)`. Implicit formatting otherwise applies only to simple
placeholders inside Literal values.
`CSliteral.resolve()` raises `ValueError` when the selected mapping has no
options or an empty option list.

`CSRecord` works with lists of dictionaries or a dictionary of dictionaries. It makes a copy of the input when it is created. For list input,
each record must produce a unique, non-missing string key. Malformed
containers, items, dictionary keys or values, missing keys, duplicate keys,
and invalid callable results raise `TypeError` or `ValueError`. The error names
the failing boundary. `data_map` is a defensive copy, and `keys` preserves
input order.
`CSRecordTemplate.resolve()` returns `dict` when its context key is absent;
otherwise it passes through the same record validation errors.

`ConditionalModel.bind()` creates a new model subclass that handles templates, records, and bind-time conditions. `json_schema()` raises `ValueError` if
called before the required binding. `propdoc(lazy=False)` also requires a
bound model. Cached schemas are bounded, and every returned schema is a
defensive copy. Uncached schemas are new dictionaries as well.

`CSField()` returns a `ConditionalFieldInfo` descriptor. Direct descriptor
construction is supported for advanced integrations, but normal model code
should use `CSField`. `Template`, `LiteralTemplate`, `CSRecordTemplate`, and
`ConditionalFieldInfo` keep their input metadata until `bind()` resolves it;
they do not mutate the caller's context mapping.

### Module and Naming Compatibility

The original `main` import path remains supported. You can also import
subsystem names from `conditions`, `templates`, `records`, and `schema`.
